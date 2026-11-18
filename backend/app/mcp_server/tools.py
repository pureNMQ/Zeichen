"""Shared MCP session helpers and the project, work, reference, and notification tools."""

import contextvars
import functools
import uuid
from typing import Literal

from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import select

from ..db import SessionLocal
from ..errors import AppError
from ..models import ProjectMember, User
from ..services import projects as project_svc
from ..services import repositories as repository_svc
from ..services import polymorphic as poly_svc
from ..services import requirements as req_svc
from ..services import tasks as task_svc
from ..services import work_trash as work_trash_svc
from ..services.work_trash import WorkKind
from ..v2 import notifications as notification_svc, work_content
from ..v2.resource_refs import parse_uuid as parse_v2_uuid
from . import auth

_ctx = contextvars.ContextVar[tuple[object, User]]("zeichen_mcp_ctx", default=None)
_UNSET = object()


def sessioned(fn):
    """会话绑定 + AppError → MCP 错误;签名不变(经 __wrapped__ 供 FastMCP 生成 schema)。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with SessionLocal() as db:
            actor = auth.current_principal(db)
            token = _ctx.set((db, actor))
            try:
                return fn(*args, **kwargs)
            except AppError as e:
                raise ToolError(f"{e.code}: {e.message}") from e
            finally:
                _ctx.reset(token)

    return wrapper


def dbc() -> tuple[SessionLocal, User]:
    return _ctx.get()


def _paged(filters: dict, cursor: str | None, limit: int | None) -> tuple[str | None, int]:
    from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

    if limit is None:
        limit = DEFAULT_PAGE_SIZE
    if limit < 1 or limit > MAX_PAGE_SIZE:
        raise ToolError("invalid_request: limit 超出范围(1-100)")
    return cursor, limit


def _req_id(requirement_id: str | None) -> str | None:
    """需求短码透传(REQ-n);格式非法 → invalid_request(ADR 0002)。"""
    if requirement_id is None or requirement_id == "":
        return requirement_id or None
    from app.services.short_codes import require_valid_code

    try:
        return require_valid_code("requirement", requirement_id)
    except AppError as exc:
        raise ToolError(f"{exc.code}: {exc.message}") from None


def _split_statuses(status: str | None) -> list[str] | None:
    """MCP status 逗号分隔字符串 → list;单值不变;None/空 → None(不过滤)。"""
    if status is None:
        return None
    parts = [s.strip() for s in status.split(",") if s.strip()]
    return parts or None


def _scope_uuid(project_id: str | None) -> uuid.UUID | None:
    """可选 project_id 解析:仅用于多态工具的 project/repository 目标(UUID 寻址)。"""
    return _optional_uuid(project_id, "project_id")


def _require_scope(project_id: str | None) -> uuid.UUID:
    """短码寻址工具必传 project_id(REQ-55 返工:统一接口,缺省项目的全局解析路径从 MCP 移除)。"""
    if project_id is None or not str(project_id).strip():
        raise ToolError("invalid_request: project_id 必传(短码按项目内寻址,不接受缺省项目)")
    return _parse_uuid(project_id, "project_id")


_ENTITY_TARGET_TYPES = ("requirement", "task", "document")


def _target_scope(project_id: str | None, target_types: tuple[str, ...]) -> uuid.UUID | None:
    """多态工具目标的项目上下文:实体短码目标必传;project/repository 目标 UUID 寻址可省。"""
    if any(t in _ENTITY_TARGET_TYPES for t in target_types):
        return _require_scope(project_id)
    return _scope_uuid(project_id)


def _optional_uuid(value: str | None, field_name: str) -> uuid.UUID | None:
    """Parse an optional MCP UUID while preserving the established empty=root semantics."""
    if value is None or value == "":
        return None
    return _parse_uuid(value, field_name)


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ToolError(f"invalid_request: {field_name} 必须是合法 UUID") from None


def _register_all(mcp) -> None:
    from .governance_tools import register_governance_tools

    register_governance_tools(mcp)
    # ---------- repositories.* ----------
    @mcp.tool(name="repositories.list")
    @sessioned
    def repositories_list(project_id: str) -> dict:
        """列出项目中未删除的代码仓库记录。"""
        db, actor = dbc()
        return {"items": repository_svc.list_repositories(db, actor, _require_scope(project_id))}

    @mcp.tool(name="repositories.deleted")
    @sessioned
    def repositories_deleted(project_id: str) -> dict:
        """列出项目中已软删除的代码仓库记录（editor+）。"""
        db, actor = dbc()
        return {"items": repository_svc.list_repositories(db, actor, _require_scope(project_id), deleted=True)}

    @mcp.tool(name="repositories.get")
    @sessioned
    def repositories_get(id: str) -> dict:
        """获取代码仓库记录。"""
        db, actor = dbc()
        return repository_svc.get_repository(db, actor, _parse_uuid(id, "id"))

    @mcp.tool(name="repositories.create")
    @sessioned
    def repositories_create(
        project_id: str,
        name: str,
        vcs_type: str,
        url: str,
        other_vcs_type: str | None = None,
        description: str | None = None,
        default_branch: str | None = None,
    ) -> dict:
        """创建项目代码仓库记录；不保存凭据，也不会连接或同步远端。"""
        db, actor = dbc()
        repository = repository_svc.create_repository(
            db, actor, _require_scope(project_id),
            {
                "name": name, "vcs_type": vcs_type, "url": url,
                "other_vcs_type": other_vcs_type, "description": description,
                "default_branch": default_branch,
            },
        )
        return repository_svc._repository_dict(repository)

    @mcp.tool(name="repositories.update")
    @sessioned
    def repositories_update(
        id: str,
        name: str | None = None,
        vcs_type: str | None = None,
        url: str | None = None,
        other_vcs_type: str | None = _UNSET,
        description: str | None = _UNSET,
        default_branch: str | None = _UNSET,
    ) -> dict:
        """更新代码仓库记录；省略可选字段时保留原值，传 null 时清空。"""
        db, actor = dbc()
        patch = {key: value for key, value in {
            "name": name, "vcs_type": vcs_type, "url": url,
            "other_vcs_type": other_vcs_type, "description": description,
            "default_branch": default_branch,
        }.items() if value is not _UNSET and (value is not None or key in {"other_vcs_type", "description", "default_branch"})}
        repository = repository_svc.update_repository(db, actor, _parse_uuid(id, "id"), patch)
        return repository_svc._repository_dict(repository)

    @mcp.tool(name="repositories.delete")
    @sessioned
    def repositories_delete(id: str) -> dict:
        """软删除代码仓库记录；不影响实际仓库。"""
        db, actor = dbc()
        repository_svc.delete_repository(db, actor, _parse_uuid(id, "id"))
        return {"deleted": True, "id": id}

    @mcp.tool(name="repositories.restore")
    @sessioned
    def repositories_restore(id: str) -> dict:
        """恢复已软删除的代码仓库记录。"""
        db, actor = dbc()
        repository = repository_svc.restore_repository(db, actor, _parse_uuid(id, "id"))
        return repository_svc._repository_dict(repository)

    @mcp.tool(name="work.versions")
    @sessioned
    def work_versions(project_id: str, kind: work_content.WorkKind, id: str, before: int | None = None, limit: int = 50) -> dict:
        """列出需求或任务的正文版本，按版本倒序，用 next_before 续页。"""
        db, actor = dbc()
        return work_content.versions(db, actor, _require_scope(project_id), kind, id, before, limit)

    @mcp.tool(name="work.read_version")
    @sessioned
    def work_read_version(project_id: str, kind: work_content.WorkKind, id: str, version: int) -> dict:
        """读取指定历史版本的标题和 Markdown 正文。"""
        db, actor = dbc()
        return work_content.version(db, actor, _require_scope(project_id), kind, id, version)

    @mcp.tool(name="work.restore_version")
    @sessioned
    def work_restore_version(project_id: str, kind: work_content.WorkKind, id: str, version: int, expected_version: int) -> dict:
        """恢复需求或任务的指定正文版本，保留中间历史并生成新版本。"""
        db, actor = dbc()
        return work_content.restore(db, actor, _require_scope(project_id), kind, id, version, expected_version)

    # ---------- requirements.* ----------
    @mcp.tool(name="requirements.create")
    @sessioned
    def requirements_create(project_id: str, title: str, description: str | None = None, request_id: uuid.UUID | None = None) -> dict:
        """创建需求；使用同一 request_id 安全重试。"""
        db, actor = dbc()
        return work_content.create(db, actor, _require_scope(project_id), "requirements", title, description, request_id)

    @mcp.tool(name="requirements.get")
    @sessioned
    def requirements_get(id: str, project_id: str) -> dict:
        """需求详情(含任务数)。project_id 必传:短码按项目内寻址,无缺省项目路径。"""
        db, actor = dbc()
        return req_svc._requirement_dict(
            db, req_svc.get_requirement(db, actor, id, project_id=_require_scope(project_id))
        )

    @mcp.tool(name="requirements.list")
    @sessioned
    def requirements_list(
        project_id: str,
        participated_by_me: bool = False,
        status: str | None = None,
        updated_within_days: int | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """需求列表，正文仅返回前 240 字，读全文用 requirements.get (cursor 分页;keyword 标题/描述包含、updated_within_days 时间窗口;
        status 多值用逗号分隔,如 status='backlog,in_progress')。"""
        db, actor = dbc()
        cursor, limit = _paged({}, cursor, limit)
        return req_svc.list_requirements(
            db, actor, _require_scope(project_id), _split_statuses(status), cursor, limit,
            updated_within_days=updated_within_days, keyword=keyword, participated_by_me=participated_by_me,
        )

    @mcp.tool(name="requirements.set_blockers")
    @sessioned
    def requirements_set_blockers(id: str, project_id: str, blocked_by: list[str],
                                 expected_blocked_by: list[str] | None = None) -> dict:
        """替换同项目需求的前置需求集合。全部前置需求已完成时解除阻塞，空列表移除依赖。"""
        from ..services.requirement_board import set_blockers

        db, actor = dbc()
        return req_svc._requirement_dict(db, set_blockers(
            db, actor, id, _require_scope(project_id), blocked_by, expected_blocked_by))

    @mcp.tool(name="requirements.update")
    @sessioned
    def requirements_update(
        id: str, project_id: str, title: str | None = None, description: str | None = None,
        expected_version: int | None = None,
    ) -> dict:
        """更新需求标题和 Markdown 正文。传读取时的 expected_version，过期返回 conflict。"""
        db, actor = dbc()
        r = req_svc.update_requirement(
            db, actor, id, title, description, project_id=_require_scope(project_id), expected_version=expected_version
        )
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.set_status")
    @sessioned
    def requirements_set_status(id: str, project_id: str, status: str) -> dict:
        """改状态:任意目标态自由流转(需求六态:pending/backlog/in_progress/verifying/done/cancelled),
        无任何前置校验;pending→backlog 即确认,verifying=验收中(验收语义在需求层)。
        project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        r = req_svc.set_requirement_status(
            db, actor, id, status, project_id=_require_scope(project_id)
        )
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.reject")
    @sessioned
    def requirements_reject(id: str, project_id: str, reason: str, request_id: str) -> dict:
        """将验收中的需求打回待办，同时记录原因。重试时请复用 request_id。"""
        db, actor = dbc()
        result = req_svc.reject_requirement(
            db, actor, _require_scope(project_id), id, reason, _parse_uuid(request_id, "request_id")
        )
        db.commit()
        return result

    @mcp.tool(name="requirements.cancel")
    @sessioned
    def requirements_cancel(id: str, project_id: str) -> dict:
        """取消需求:set_status('cancelled') 便捷封装。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        r = req_svc.cancel_requirement(db, actor, id, project_id=_require_scope(project_id))
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.delete")
    @sessioned
    def requirements_delete(
        id: str, project_id: str, confirm_task_count: int | None = None
    ) -> dict:
        """软删需求;下有任务时须传 confirm_task_count=任务数 二次确认。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        req_svc.delete_requirement(
            db, actor, id, confirm_task_count, project_id=_require_scope(project_id)
        )
        return {"deleted": True, "id": id}

    @mcp.tool(name="requirements.restore")
    @sessioned
    def requirements_restore(id: str, project_id: str) -> dict:
        """恢复已软删需求。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return req_svc._requirement_dict(
            db, req_svc.restore_requirement(db, actor, id, project_id=_require_scope(project_id))
        )

    # ---------- tasks.* ----------
    @mcp.tool(name="tasks.create")
    @sessioned
    def tasks_create(
        project_id: str,
        title: str,
        description: str | None = None,
        requirement_id: str | None = None,
        assignee_id: str | None = None,
        request_id: uuid.UUID | None = None,
    ) -> dict:
        """在指定需求内创建任务，返回 REQ-n-Tm 短码。"""
        db, actor = dbc()
        return work_content.create(db, actor, _require_scope(project_id), "tasks", title, description, request_id,
                                   requirement_id=_req_id(requirement_id), assignee_id=_optional_uuid(assignee_id, "assignee_id"))

    @mcp.tool(name="tasks.get")
    @sessioned
    def tasks_get(id: str, project_id: str) -> dict:
        """任务详情。project_id 必传:短码按项目内寻址,无缺省项目路径。"""
        db, actor = dbc()
        return task_svc._task_dict(
            db, task_svc.get_task(db, actor, id, project_id=_require_scope(project_id))
        )

    @mcp.tool(name="tasks.list")
    @sessioned
    def tasks_list(
        project_id: str,
        requirement_id: str | None = None,
        assignee_id: str | None = None,
        status: str | None = None,
        updated_within_days: int | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """任务列表，正文仅返回前 240 字，读全文用 tasks.get (多维度过滤,cursor 分页;keyword 标题/描述包含、updated_within_days 时间窗口;
        status 多值用逗号分隔,如 status='backlog,in_progress')。"""
        db, actor = dbc()
        cursor, limit = _paged({}, cursor, limit)
        return task_svc.list_tasks(
            db, actor, _require_scope(project_id), _req_id(requirement_id),
            _optional_uuid(assignee_id, "assignee_id"),
            _split_statuses(status), cursor, limit,
            updated_within_days=updated_within_days, keyword=keyword,
        )

    @mcp.tool(name="tasks.update")
    @sessioned
    def tasks_update(
        id: str,
        project_id: str,
        title: str | None = None,
        description: str | None = None,
        expected_version: int | None = None,
    ) -> dict:
        """更新任务标题和 Markdown 正文。传读取时的 expected_version，过期返回 conflict。"""
        db, actor = dbc()
        t = task_svc.update_task(
            db, actor, id, title, description, project_id=_require_scope(project_id), expected_version=expected_version
        )
        return task_svc._task_dict(db, t)

    @mcp.tool(name="tasks.set_status")
    @sessioned
    def tasks_set_status(id: str, project_id: str, status: str) -> dict:
        """改状态:任意目标态自由流转(任务四态:backlog/in_progress/done/cancelled);已指派仅本人/管理员。
        project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        t = task_svc.set_task_status(
            db, actor, id, status, project_id=_require_scope(project_id)
        )
        return task_svc._task_dict(db, t)

    @mcp.tool(name="tasks.assign")
    @sessioned
    def tasks_assign(id: str, project_id: str, assignee_id: str) -> dict:
        """指派(未指派任意编辑权者可指派;已指派仅本人/管理员可改派)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return task_svc._task_dict(
            db,
            task_svc.assign_task(
                db, actor, id, _parse_uuid(assignee_id, "assignee_id"), project_id=_require_scope(project_id)
            ),
        )

    @mcp.tool(name="tasks.claim")
    @sessioned
    def tasks_claim(id: str, project_id: str) -> dict:
        """认领未指派任务(并发安全,失败得 conflict)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return task_svc._task_dict(
            db, task_svc.claim_task(db, actor, id, project_id=_require_scope(project_id))
        )

    @mcp.tool(name="tasks.unassign")
    @sessioned
    def tasks_unassign(id: str, project_id: str) -> dict:
        """解除指派(仅本人/管理员)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return task_svc._task_dict(
            db, task_svc.unassign_task(db, actor, id, project_id=_require_scope(project_id))
        )

    @mcp.tool(name="tasks.cancel")
    @sessioned
    def tasks_cancel(id: str, project_id: str) -> dict:
        """取消任务:set_status('cancelled') 便捷封装。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return task_svc._task_dict(
            db, task_svc.cancel_task(db, actor, id, project_id=_require_scope(project_id))
        )

    @mcp.tool(name="tasks.delete")
    @sessioned
    def tasks_delete(id: str, project_id: str) -> dict:
        """软删任务(已指派仅本人/管理员)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        task_svc.delete_task(db, actor, id, project_id=_require_scope(project_id))
        return {"deleted": True, "id": id}

    @mcp.tool(name="tasks.restore")
    @sessioned
    def tasks_restore(id: str, project_id: str) -> dict:
        """恢复已软删任务。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return task_svc._task_dict(
            db, task_svc.restore_task(db, actor, id, project_id=_require_scope(project_id))
        )

    # ---------- retained legacy comment history ----------
    @mcp.tool(name="comment.list")
    @sessioned
    def comment_list(
        target_type: str, target_id: str, cursor: str | None = None,
        limit: int | None = None, project_id: str | None = None,
    ) -> dict:
        """只读查看迁移保留的旧评论(cursor 分页)。需求当前时间轴请使用 timeline.list。
        实体目标(短码寻址)必传 project_id;project 目标(UUID 寻址)可省。"""
        db, actor = dbc()
        cursor, limit = _paged({"type": target_type, "id": target_id}, cursor, limit)
        scope = _target_scope(project_id, (target_type,))
        if target_type == "document":
            poly_svc.resolve_reference_target(db, actor, target_type, target_id, scope)
        return poly_svc.list_comments(
            db, actor, target_type, target_id, cursor, limit,
            project_id=scope,
        )

    # ---------- Markdown backlinks ----------
    @mcp.tool(name="markdown.backlinks")
    @sessioned
    def markdown_backlinks(project_id: str, target_kind: Literal["requirements", "tasks", "wiki"],
                           target_id: str, cursor: str | None = None, limit: int = 50) -> dict:
        """读取当前需求、任务和 Wiki 正文中指向目标的反向链接。通过编辑来源正文添加或移除链接。"""
        from ..v2.backlinks import list_backlinks
        db, actor = dbc()
        return list_backlinks(db, actor, _parse_uuid(project_id, "project_id"), target_kind, target_id, cursor, limit)

    # ---------- project.* / agent.* ----------
    @mcp.tool(name="project.list")
    @sessioned
    def project_list() -> list[dict]:
        """我有权限的项目列表(admin 全量;否则已加入)。"""
        db, actor = dbc()
        return project_svc.project_directory(db, actor)

    @mcp.tool(name="project.get")
    @sessioned
    def project_get(id: str) -> dict:
        """项目详情(非成员 404)。"""
        db, actor = dbc()
        project, role = project_svc.get_project(db, actor, _parse_uuid(id, "id"))
        return project_svc.project_summary(project, role)

    @mcp.tool(name="trash.projects_list")
    @sessioned
    def trash_projects_list(q: str = "", cursor: str | None = None, limit: int = 20) -> dict:
        """列出当前管理员或项目负责人有权恢复的已删除项目。"""
        db, actor = dbc()
        return project_svc.list_deleted_projects(db, actor, q=q, cursor=cursor, limit=limit)

    @mcp.tool(name="trash.projects_get")
    @sessioned
    def trash_projects_get(id: str) -> dict:
        """查看已删除项目的删除信息和业务对象数量。"""
        db, actor = dbc()
        return project_svc.project_delete_impact(db, actor, _parse_uuid(id, "id"), deleted=True)

    @mcp.tool(name="trash.projects_restore")
    @sessioned
    def trash_projects_restore(id: str) -> dict:
        """恢复项目及随项目暂时隐藏的活动内容；独立删除项保持删除。"""
        db, actor = dbc()
        return project_svc.restore_project(db, actor, _parse_uuid(id, "id"))

    @mcp.tool(name="trash.work_list")
    @sessioned
    def trash_work_list(
        project_id: str, kind: WorkKind, keyword: str = "", cursor: str | None = None, limit: int = 20,
    ) -> dict:
        """发现当前项目中明确删除的需求或任务。"""
        db, actor = dbc()
        return work_trash_svc.list_deleted_work(
            db, actor, parse_v2_uuid(project_id, "project_id"), kind,
            keyword=keyword, cursor=cursor, limit=limit,
        )

    @mcp.tool(name="trash.work_get")
    @sessioned
    def trash_work_get(project_id: str, kind: WorkKind, id: str) -> dict:
        """查看已删除工作项及受父项删除影响的任务计数。"""
        db, actor = dbc()
        return work_trash_svc.deleted_work_details(db, actor, parse_v2_uuid(project_id, "project_id"), kind, id)

    @mcp.tool(name="trash.work_restore")
    @sessioned
    def trash_work_restore(project_id: str, kind: WorkKind, id: str) -> dict:
        """恢复项目内工作项；父需求未恢复时返回冲突。"""
        db, actor = dbc()
        return work_trash_svc.restore_work(db, actor, parse_v2_uuid(project_id, "project_id"), kind, id)

    @mcp.tool(name="agent.whoami")
    @sessioned
    def agent_whoami() -> dict:
        """当前 agent 身份、宿主与项目授权(ADR 0004:权限动态继承主人)。"""
        db, actor = dbc()
        owner = db.get(User, actor.owner_id) if actor.owner_id else None
        projects = project_svc.list_projects(db, actor)
        return {
            "id": str(actor.id),
            "username": actor.username,
            "is_agent": actor.is_agent,
            "owner": (
                {
                    "id": str(owner.id),
                    "username": owner.username,
                    "nickname": owner.nickname,
                }
                if owner is not None
                else None
            ),
            "project_grants": [{"project_id": str(p.id), "role": role} for p, role in projects],
        }

    # ---------- notifications.* ----------
    @mcp.tool(name="notifications.list")
    @sessioned
    def notifications_list(cursor: str | None = None, limit: int = 20, unread_only: bool = False) -> dict:
        """读取共享提及/回复通知；列表读取不标记已读，使用 next_cursor 继续。"""
        db, actor = dbc()
        return notification_svc.list_notifications(db, actor, cursor=cursor, limit=limit, unread_only=unread_only)

    @mcp.tool(name="notifications.unread_count")
    @sessioned
    def notifications_unread_count() -> dict:
        """统计当前 Agent 可见的未读通知，保留仅主人可见通知的隐私。"""
        db, actor = dbc()
        return {"count": notification_svc.unread_count(db, actor)}

    @mcp.tool(name="notifications.get")
    @sessioned
    def notifications_get(id: str) -> dict:
        """获取一条仍可访问的共享通知；读取详情不标记已读。"""
        db, actor = dbc()
        return notification_svc.get_notification(db, actor, parse_v2_uuid(id, "id"))

    @mcp.tool(name="notifications.mark_read")
    @sessioned
    def notifications_mark_read(id: str) -> dict:
        """显式确认共享通知；主人和 Agent 共用第一次确认记录。"""
        db, actor = dbc()
        result = notification_svc.mark_read(db, actor, parse_v2_uuid(id, "id"))
        db.commit()
        return {"id": result["id"], "read_at": result["read_at"], "read_by_id": result["read_by_id"]}
