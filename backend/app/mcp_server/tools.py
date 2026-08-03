"""MCP 工具集:requirements.* / tasks.* / comment.* / ref.* / project.* / agent.*(28 工具)。

- 每个工具复用 backend service 层,错误四件套映射为 MCP 错误消息前缀 `code: message`
- cursor 分页统一(pagination.py);删除类 = 软删 + restore
- 点号命名空间 + 小写工具名(规格书 §4.1)
"""

import contextvars
import functools
import uuid

from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import select

from ..db import SessionLocal
from ..errors import AppError
from ..models import ProjectMember, User
from ..services import projects as project_svc
from ..services import polymorphic as poly_svc
from ..services import requirements as req_svc
from ..services import tasks as task_svc
from . import auth

_ctx = contextvars.ContextVar[tuple[object, User]]("zeichen_mcp_ctx", default=None)


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


def _req_id(requirement_id: str | None) -> uuid.UUID | None:
    return uuid.UUID(requirement_id) if requirement_id else None


def _register_all(mcp) -> None:
    # ---------- requirements.* ----------
    @mcp.tool(name="requirements.create")
    @sessioned
    def requirements_create(project_id: str, title: str, description: str | None = None) -> dict:
        """创建需求(状态=待办)。"""
        db, actor = dbc()
        r = req_svc.create_requirement(db, actor, uuid.UUID(project_id), title, description)
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.get")
    @sessioned
    def requirements_get(id: str) -> dict:
        """需求详情(含任务数)。"""
        db, actor = dbc()
        return req_svc._requirement_dict(db, req_svc.get_requirement(db, actor, uuid.UUID(id)))

    @mcp.tool(name="requirements.list")
    @sessioned
    def requirements_list(
        project_id: str, status: str | None = None, cursor: str | None = None, limit: int | None = None
    ) -> dict:
        """需求列表(可按状态过滤,cursor 分页)。"""
        db, actor = dbc()
        cursor, limit = _paged({"project_id": project_id, "status": status}, cursor, limit)
        return req_svc.list_requirements(db, actor, uuid.UUID(project_id), status, cursor, limit)

    @mcp.tool(name="requirements.update")
    @sessioned
    def requirements_update(id: str, title: str | None = None, description: str | None = None) -> dict:
        """更新需求元数据(标题/描述,不涉状态)。"""
        db, actor = dbc()
        r = req_svc.update_requirement(db, actor, uuid.UUID(id), title, description)
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.set_status")
    @sessioned
    def requirements_set_status(id: str, status: str) -> dict:
        """改状态:任意目标态自由流转(backlog/in_progress/done/cancelled),无任何前置校验;状态全手动。"""
        db, actor = dbc()
        r = req_svc.set_requirement_status(db, actor, uuid.UUID(id), status)
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.cancel")
    @sessioned
    def requirements_cancel(id: str) -> dict:
        """取消需求:set_status('cancelled') 便捷封装。"""
        db, actor = dbc()
        r = req_svc.cancel_requirement(db, actor, uuid.UUID(id))
        return req_svc._requirement_dict(db, r)

    @mcp.tool(name="requirements.delete")
    @sessioned
    def requirements_delete(id: str, confirm_task_count: int | None = None) -> dict:
        """软删需求;下有任务时须传 confirm_task_count=任务数 二次确认。"""
        db, actor = dbc()
        req_svc.delete_requirement(db, actor, uuid.UUID(id), confirm_task_count)
        return {"deleted": True, "id": id}

    @mcp.tool(name="requirements.restore")
    @sessioned
    def requirements_restore(id: str) -> dict:
        """恢复已软删需求。"""
        db, actor = dbc()
        return req_svc._requirement_dict(db, req_svc.restore_requirement(db, actor, uuid.UUID(id)))

    # ---------- tasks.* ----------
    @mcp.tool(name="tasks.create")
    @sessioned
    def tasks_create(
        project_id: str,
        title: str,
        description: str | None = None,
        requirement_id: str | None = None,
        assignee_id: str | None = None,
    ) -> dict:
        """创建任务(requirement_id 可空=独立任务;assignee_id 可空=待认领)。"""
        db, actor = dbc()
        t = task_svc.create_task(
            db, actor, uuid.UUID(project_id), title, description,
            _req_id(requirement_id), _req_id(assignee_id),
        )
        return task_svc._task_dict(db, t)

    @mcp.tool(name="tasks.get")
    @sessioned
    def tasks_get(id: str) -> dict:
        """任务详情。"""
        db, actor = dbc()
        return task_svc._task_dict(db, task_svc.get_task(db, actor, uuid.UUID(id)))

    @mcp.tool(name="tasks.list")
    @sessioned
    def tasks_list(
        project_id: str,
        requirement_id: str | None = None,
        assignee_id: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """任务列表(多维度过滤,cursor 分页)。"""
        db, actor = dbc()
        filters = {
            "project_id": project_id, "requirement_id": requirement_id,
            "assignee_id": assignee_id, "status": status,
        }
        cursor, limit = _paged(filters, cursor, limit)
        return task_svc.list_tasks(
            db, actor, uuid.UUID(project_id), _req_id(requirement_id),
            _req_id(assignee_id), status, cursor, limit,
        )

    @mcp.tool(name="tasks.update")
    @sessioned
    def tasks_update(
        id: str,
        title: str | None = None,
        description: str | None = None,
        requirement_id: str | None = None,
    ) -> dict:
        """更新任务元数据(标题/描述/关联需求;requirement_id 传空=解除关联,须与任务同项目且未删除)。"""
        db, actor = dbc()
        t = task_svc.update_task(
            db, actor, uuid.UUID(id), title, description, _req_id(requirement_id)
        )
        return task_svc._task_dict(db, t)

    @mcp.tool(name="tasks.set_status")
    @sessioned
    def tasks_set_status(id: str, status: str) -> dict:
        """改状态:任意目标态自由流转(backlog/in_progress/verifying/done/cancelled);已指派仅本人/管理员。"""
        db, actor = dbc()
        t = task_svc.set_task_status(db, actor, uuid.UUID(id), status)
        return task_svc._task_dict(db, t)

    @mcp.tool(name="tasks.assign")
    @sessioned
    def tasks_assign(id: str, assignee_id: str) -> dict:
        """指派(未指派任意编辑权者可指派;已指派仅本人/管理员可改派)。"""
        db, actor = dbc()
        return task_svc._task_dict(db, task_svc.assign_task(db, actor, uuid.UUID(id), uuid.UUID(assignee_id)))

    @mcp.tool(name="tasks.claim")
    @sessioned
    def tasks_claim(id: str) -> dict:
        """认领未指派任务(并发安全,失败得 conflict)。"""
        db, actor = dbc()
        return task_svc._task_dict(db, task_svc.claim_task(db, actor, uuid.UUID(id)))

    @mcp.tool(name="tasks.unassign")
    @sessioned
    def tasks_unassign(id: str) -> dict:
        """解除指派(仅本人/管理员)。"""
        db, actor = dbc()
        return task_svc._task_dict(db, task_svc.unassign_task(db, actor, uuid.UUID(id)))

    @mcp.tool(name="tasks.cancel")
    @sessioned
    def tasks_cancel(id: str) -> dict:
        """取消任务:set_status('cancelled') 便捷封装。"""
        db, actor = dbc()
        return task_svc._task_dict(db, task_svc.cancel_task(db, actor, uuid.UUID(id)))

    @mcp.tool(name="tasks.delete")
    @sessioned
    def tasks_delete(id: str) -> dict:
        """软删任务(已指派仅本人/管理员)。"""
        db, actor = dbc()
        task_svc.delete_task(db, actor, uuid.UUID(id))
        return {"deleted": True, "id": id}

    @mcp.tool(name="tasks.restore")
    @sessioned
    def tasks_restore(id: str) -> dict:
        """恢复已软删任务。"""
        db, actor = dbc()
        return task_svc._task_dict(db, task_svc.restore_task(db, actor, uuid.UUID(id)))

    # ---------- comment.* ----------
    @mcp.tool(name="comment.create")
    @sessioned
    def comment_create(target_type: str, target_id: str, body: str) -> dict:
        """在实体上添加评论(requirement/task/document/project)。"""
        db, actor = dbc()
        c = poly_svc.create_comment(db, actor, target_type, uuid.UUID(target_id), body)
        return {"id": str(c.id), "target_type": c.target_type, "target_id": str(c.target_id), "body": c.body}

    @mcp.tool(name="comment.list")
    @sessioned
    def comment_list(target_type: str, target_id: str, cursor: str | None = None, limit: int | None = None) -> dict:
        """实体的评论流(cursor 分页)。"""
        db, actor = dbc()
        cursor, limit = _paged({"type": target_type, "id": target_id}, cursor, limit)
        return poly_svc.list_comments(db, actor, target_type, uuid.UUID(target_id), cursor, limit)

    @mcp.tool(name="comment.delete")
    @sessioned
    def comment_delete(id: str) -> dict:
        """删除评论(仅自己的;owner/admin 任意)。"""
        db, actor = dbc()
        poly_svc.delete_comment(db, actor, uuid.UUID(id))
        return {"deleted": True, "id": id}

    # ---------- ref.* ----------
    @mcp.tool(name="ref.create")
    @sessioned
    def ref_create(from_type: str, from_id: str, to_type: str, to_id: str, type: str) -> dict:
        """建立实体间引用(type: derives/documents/implements/mentions;双方须同项目)。"""
        db, actor = dbc()
        r = poly_svc.create_reference(
            db, actor, from_type, uuid.UUID(from_id), to_type, uuid.UUID(to_id), type
        )
        return {
            "id": str(r.id), "from_type": r.from_type, "from_id": str(r.from_id),
            "to_type": r.to_type, "to_id": str(r.to_id), "type": r.type,
        }

    @mcp.tool(name="ref.list")
    @sessioned
    def ref_list(target_type: str, target_id: str, cursor: str | None = None, limit: int | None = None) -> dict:
        """实体的引用(双向:from/to 任一命中)。"""
        db, actor = dbc()
        cursor, limit = _paged({"type": target_type, "id": target_id}, cursor, limit)
        return poly_svc.list_references(db, actor, target_type, uuid.UUID(target_id), cursor, limit)

    @mcp.tool(name="ref.delete")
    @sessioned
    def ref_delete(id: str) -> dict:
        """删除引用。"""
        db, actor = dbc()
        poly_svc.delete_reference(db, actor, uuid.UUID(id))
        return {"deleted": True, "id": id}

    # ---------- project.* / agent.* ----------
    @mcp.tool(name="project.list")
    @sessioned
    def project_list() -> list[dict]:
        """我有权限的项目列表(admin 全量;否则已加入)。"""
        db, actor = dbc()
        return [
            {"id": str(p.id), "name": p.name, "my_role": role}
            for p, role in project_svc.list_projects(db, actor)
        ]

    @mcp.tool(name="project.get")
    @sessioned
    def project_get(id: str) -> dict:
        """项目详情(非成员 404)。"""
        db, actor = dbc()
        project, role = project_svc.get_project(db, actor, uuid.UUID(id))
        return {"id": str(project.id), "name": project.name, "my_role": role}

    @mcp.tool(name="agent.whoami")
    @sessioned
    def agent_whoami() -> dict:
        """当前 agent 身份与项目授权。"""
        db, actor = dbc()
        grants = db.execute(
            select(ProjectMember.role, ProjectMember.project_id).where(
                ProjectMember.user_id == actor.id
            )
        ).all()
        return {
            "id": str(actor.id),
            "username": actor.username,
            "is_agent": actor.is_agent,
            "project_grants": [{"project_id": str(p), "role": r} for r, p in grants],
        }
