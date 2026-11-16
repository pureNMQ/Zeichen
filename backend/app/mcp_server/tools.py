"""MCP 工具集:requirements.* / tasks.* / docs.wiki.* / comment.* / ref.* / project.* / agent.*(51 工具)。

- 每个工具复用 backend service 层,错误四件套映射为 MCP 错误消息前缀 `code: message`
- cursor 分页统一(pagination.py);删除类 = 软删 + restore
- 点号命名空间 + 小写工具名(规格书 §4.1)
- REQ-59:glossary 并入 wiki,docs.glossary.* 下线;新增 docs.wiki.index / docs.search;
  docs.wiki.get 聚合返回正文+元数据+双链+反链
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
from ..services import documents as document_svc
from ..services import repositories as repository_svc
from ..services import polymorphic as poly_svc
from ..services import requirements as req_svc
from ..services import tasks as task_svc
from ..services import search as search_svc
from ..services import attachments as attachment_svc
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


def _uuid_list(values: list[str] | None) -> list[str] | None:
    """MCP blocked_by:任务短码列表(TASK-n);None/[] 原样传递(None/[]=清空语义)。"""
    if values is None:
        return None
    from app.services.short_codes import require_valid_code

    result: list[str] = []
    for value in values:
        try:
            result.append(require_valid_code("task", value))
        except AppError:
            raise ToolError("invalid_request: blocked_by 必须是合法任务短码(TASK-n)列表") from None
    return result


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

    # ---------- requirements.* ----------
    @mcp.tool(name="requirements.create")
    @sessioned
    def requirements_create(project_id: str, title: str, description: str | None = None) -> dict:
        """创建需求(状态=待确认)。"""
        db, actor = dbc()
        r = req_svc.create_requirement(db, actor, _require_scope(project_id), title, description)
        return req_svc._requirement_dict(db, r)

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
        status: str | None = None,
        updated_within_days: int | None = None,
        keyword: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """需求列表(cursor 分页;keyword 标题/描述包含、updated_within_days 时间窗口;
        status 多值用逗号分隔,如 status='backlog,in_progress')。"""
        db, actor = dbc()
        cursor, limit = _paged({}, cursor, limit)
        return req_svc.list_requirements(
            db, actor, _require_scope(project_id), _split_statuses(status), cursor, limit,
            updated_within_days=updated_within_days, keyword=keyword,
        )

    @mcp.tool(name="requirements.update")
    @sessioned
    def requirements_update(
        id: str, project_id: str, title: str | None = None, description: str | None = None,
    ) -> dict:
        """更新需求元数据(标题/描述,不涉状态)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        r = req_svc.update_requirement(
            db, actor, id, title, description, project_id=_require_scope(project_id)
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
        blocked_by: list[str] | None = None,
    ) -> dict:
        """创建任务(requirement_id 必填=同项目已确认需求,缺失返回 invalid_request;
        assignee_id 可空=待认领;blocked_by=前置任务 id 列表,仅同项目)。"""
        db, actor = dbc()
        t = task_svc.create_task(
            db, actor, _require_scope(project_id), title, description,
            _req_id(requirement_id),
            _optional_uuid(assignee_id, "assignee_id"),
            _uuid_list(blocked_by),
        )
        return task_svc._task_dict(db, t)

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
        """任务列表(多维度过滤,cursor 分页;keyword 标题/描述包含、updated_within_days 时间窗口;
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
        requirement_id: str | None = _UNSET,
        blocked_by: list[str] | None = _UNSET,
    ) -> dict:
        """更新任务元数据；省略 requirement_id/blocked_by 保留原值，requirement_id 仅可改指向
        同项目其他需求(传 null/空字符串解除关联会被拒绝，任务必须挂需求)，blocked_by 传 null
        或 [] 清空(整体替换)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        kwargs: dict = {}
        if requirement_id is not _UNSET:
            kwargs["requirement_id"] = _req_id(requirement_id)
        if blocked_by is not _UNSET:
            kwargs["blocked_by"] = _uuid_list(blocked_by)
        t = task_svc.update_task(
            db, actor, id, title, description, project_id=_require_scope(project_id), **kwargs
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

    # ---------- docs.wiki.* ----------
    def _doc_create(project_id: str, title: str, module: str, content: str, metadata: dict | None, parent_id: str | None = None) -> dict:
        db, actor = dbc()
        document, link_warning = document_svc.create_document(
            db, actor, _require_scope(project_id), title, module, content, metadata,
            parent_id or None,
        )
        return document_svc._document_dict(db, document, warning=link_warning, with_links=True)

    def _doc_get(id: str, module: str, project_id: str) -> dict:
        db, actor = dbc()
        return document_svc._document_dict(
            db,
            document_svc.get_document(db, actor, id, module, project_id=_require_scope(project_id)),
            with_links=True,
        )

    def _doc_children(project_id: str, module: str, parent_id: str | None, cursor: str | None, limit: int | None) -> dict:
        db, actor = dbc()
        cursor, limit = _paged({"project_id": project_id, "module": module, "parent_id": parent_id}, cursor, limit)
        return document_svc.list_module_children(db, actor, _require_scope(project_id), module, parent_id or None, cursor, limit)

    def _doc_update(
        id: str, module: str, title: str | None, content: str | None,
        metadata: dict | None = None, project_id: str = "",
    ) -> dict:
        db, actor = dbc()
        scope = _require_scope(project_id)
        document = document_svc.get_document(db, actor, id, module, project_id=scope)
        saved, link_warning = document_svc.update_document(
            db, actor, document.code, title, content,
            metadata if metadata is not None else document_svc._UNSET, project_id=scope,
        )
        return document_svc._document_dict(db, saved, warning=link_warning, with_links=True)

    def _doc_move(
        id: str, module: str, parent_id: str = "",
        project_id: str = "",
    ) -> dict:
        db, actor = dbc()
        scope = _require_scope(project_id)
        document = document_svc.get_document(db, actor, id, module, project_id=scope)
        moved = document_svc.move_document(
            db, actor, document.code, parent_id or None, project_id=scope
        )
        return document_svc._document_dict(db, moved)

    def _doc_delete(id: str, module: str, project_id: str) -> dict:
        db, actor = dbc()
        scope = _require_scope(project_id)
        document = document_svc.get_document(db, actor, id, module, project_id=scope)
        impact = document_svc.delete_impact_document(db, actor, document.code, project_id=scope)
        document_svc.delete_document(db, actor, document.code, project_id=scope)
        return {"deleted": True, "id": id, "impact": impact}

    def _doc_restore(id: str, module: str, project_id: str) -> dict:
        db, actor = dbc()
        scope = _require_scope(project_id)
        document = document_svc._visible_document(
            db, actor, id, include_deleted=True, project_id=scope
        )
        if document.doc_type != module:
            raise ToolError("not_found: 文档不存在")
        return document_svc._document_dict(
            db, document_svc.restore_document(db, actor, document.code, project_id=scope)
        )

    def _doc_path(project_id: str, module: str, node_kind: str, id: str) -> dict:
        db, actor = dbc()
        return document_svc.ancestor_path(db, actor, _require_scope(project_id), module, node_kind, id)

    @mcp.tool(name="docs.wiki.create")
    @sessioned
    def docs_wiki_create(project_id: str, title: str, content: str = "", parent_id: str | None = None, metadata: dict | None = None) -> dict:
        """创建根 Wiki 或指定父 Wiki 下的子 Wiki。

        正文顶部可带 YAML frontmatter(summary/doc_kind/tags/aliases),
        写入时解析合并进 metadata;[[双链]]写入时落表,断链在返回的 link_warnings。"""
        return _doc_create(project_id, title, "wiki", content, metadata, parent_id=parent_id)

    @mcp.tool(name="docs.wiki.get")
    @sessioned
    def docs_wiki_get(id: str, project_id: str) -> dict:
        """Wiki 详情:正文+frontmatter 元数据+正向链接(含断链)+反向链接(谁链我)。
        project_id 必传:短码按项目内寻址。"""
        return _doc_get(id, "wiki", project_id)

    @mcp.tool(name="docs.wiki.index")
    @sessioned
    def docs_wiki_index(project_id: str) -> dict:
        """项目知识 INDEX(后端投影,零维护):doc_kind 分节+未分类兜底,
        每页一行(短码/标题/summary/更新时间/溯源);附带 lint 信号
        (missing_kind/missing_summary/broken_links)。读路径:先读 INDEX 再钻页。"""
        db, actor = dbc()
        return document_svc.project_index(db, actor, _require_scope(project_id))

    @mcp.tool(name="docs.search")
    @sessioned
    def docs_search(project_id: str, q: str, limit: int | None = None, cursor: str | None = None) -> dict:
        """项目内 wiki 关键词检索(多关键词 AND,标题/正文/别名参与):
        返回与 INDEX 行同构的结果(短码/标题/doc_kind/summary/命中片段),cursor 分页。
        INDEX 未覆盖(词没进目录/跨概念)时用此工具兜底定位。"""
        db, actor = dbc()
        return search_svc.search_documents_paged(
            db, actor, _require_scope(project_id), q, cursor=cursor, limit=limit
        )

    @mcp.tool(name="docs.wiki.children")
    @sessioned
    def docs_wiki_children(project_id: str, parent_id: str | None = None, cursor: str | None = None, limit: int | None = None) -> dict:
        """按父 Wiki 懒加载直接子节点，返回 has_children。"""
        return _doc_children(project_id, "wiki", parent_id, cursor, limit)

    @mcp.tool(name="docs.wiki.list")
    @sessioned
    def docs_wiki_list(project_id: str, cursor: str | None = None, limit: int | None = None) -> dict:
        """根 Wiki 列表（children 的根节点别名）。"""
        return _doc_children(project_id, "wiki", None, cursor, limit)

    @mcp.tool(name="docs.wiki.ancestors")
    @sessioned
    def docs_wiki_ancestors(project_id: str, id: str) -> dict:
        return _doc_path(project_id, "wiki", "document", id)

    @mcp.tool(name="docs.wiki.update")
    @sessioned
    def docs_wiki_update(
        id: str, project_id: str, title: str | None = None, content: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        """更新 Wiki(正文 frontmatter 写入时解析合并进 metadata;[[双链]]落表)。
        project_id 必传:短码按项目内寻址。"""
        return _doc_update(id, "wiki", title, content, metadata=metadata, project_id=project_id)

    @mcp.tool(name="docs.wiki.move")
    @sessioned
    def docs_wiki_move(id: str, project_id: str, parent_id: str = "") -> dict:
        """移动 Wiki;省略 parent_id 或传空字符串移动到根节点。project_id 必传:短码按项目内寻址。"""
        return _doc_move(id, "wiki", parent_id=parent_id, project_id=project_id)

    @mcp.tool(name="docs.wiki.versions")
    @sessioned
    def docs_wiki_versions(id: str, project_id: str) -> dict:
        """Wiki 版本列表。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        return {
            "items": document_svc.list_versions(
                db, actor, id, "wiki", project_id=_require_scope(project_id)
            )
        }

    @mcp.tool(name="docs.wiki.rollback")
    @sessioned
    def docs_wiki_rollback(id: str, project_id: str, version_no: int) -> dict:
        """回滚 Wiki 版本(双链按回滚后正文重建)。project_id 必传:短码按项目内寻址。"""
        db, actor = dbc()
        rolled, link_warning = document_svc.rollback_document(
            db, actor, id, version_no, "wiki", project_id=_require_scope(project_id)
        )
        return document_svc._document_dict(db, rolled, warning=link_warning, with_links=True)

    @mcp.tool(name="docs.wiki.delete")
    @sessioned
    def docs_wiki_delete(id: str, project_id: str) -> dict:
        """删除 Wiki。project_id 必传:短码按项目内寻址。"""
        return _doc_delete(id, "wiki", project_id)

    @mcp.tool(name="docs.wiki.restore")
    @sessioned
    def docs_wiki_restore(id: str, project_id: str) -> dict:
        """恢复已删 Wiki。project_id 必传:短码按项目内寻址。"""
        return _doc_restore(id, "wiki", project_id)

    # REQ-59:glossary 并入 wiki,docs.glossary.* 工具组与目录工具下线;
    # 词条成为普通 wiki 页(TERM-n 短码保留,经 docs.wiki.* 泛型寻址)。

    # ---------- comment.* ----------
    @mcp.tool(name="comment.create")
    @sessioned
    def comment_create(
        target_type: str, target_id: str, body: str, project_id: str | None = None
    ) -> dict:
        """在实体上添加评论(requirement/document/project;task 目标返回 invalid_request,任务无评论区)。
        实体目标(短码寻址)必传 project_id;project 目标(UUID 寻址)可省。"""
        db, actor = dbc()
        c = poly_svc.create_comment(
            db, actor, target_type, target_id, body, project_id=_target_scope(project_id, (target_type,))
        )
        return {"id": str(c.id), "target_type": c.target_type, "target_id": str(c.target_id), "body": c.body}

    @mcp.tool(name="comment.list")
    @sessioned
    def comment_list(
        target_type: str, target_id: str, cursor: str | None = None,
        limit: int | None = None, project_id: str | None = None,
    ) -> dict:
        """实体的评论流(cursor 分页;task 目标返回 invalid_request,任务无评论区)。
        实体目标(短码寻址)必传 project_id;project 目标(UUID 寻址)可省。"""
        db, actor = dbc()
        cursor, limit = _paged({"type": target_type, "id": target_id}, cursor, limit)
        return poly_svc.list_comments(
            db, actor, target_type, target_id, cursor, limit,
            project_id=_target_scope(project_id, (target_type,)),
        )

    @mcp.tool(name="comment.delete")
    @sessioned
    def comment_delete(id: str) -> dict:
        """删除评论(仅自己的;owner/admin 任意)。"""
        db, actor = dbc()
        poly_svc.delete_comment(db, actor, _parse_uuid(id, "id"))
        return {"deleted": True, "id": id}

    # ---------- ref.* ----------
    @mcp.tool(name="ref.create")
    @sessioned
    def ref_create(
        from_type: str, from_id: str, to_type: str, to_id: str, type: str,
        project_id: str | None = None,
    ) -> dict:
        """建立实体间引用(type: derives/documents/implements/mentions;双方须同项目)。
        实体目标(短码寻址)必传 project_id;project/repository 目标(UUID 寻址)可省。"""
        db, actor = dbc()
        r = poly_svc.create_reference(
            db, actor, from_type, from_id, to_type, to_id, type,
            project_id=_target_scope(project_id, (from_type, to_type)),
        )
        return {
            "id": str(r.id), "from_type": r.from_type, "from_id": r.from_id,
            "to_type": r.to_type, "to_id": r.to_id, "type": r.type,
        }

    @mcp.tool(name="ref.list")
    @sessioned
    def ref_list(
        target_type: str, target_id: str, cursor: str | None = None,
        limit: int | None = None, project_id: str | None = None,
    ) -> dict:
        """实体的引用(双向:from/to 任一命中)。
        实体目标(短码寻址)必传 project_id;project/repository 目标(UUID 寻址)可省。"""
        db, actor = dbc()
        cursor, limit = _paged({"type": target_type, "id": target_id}, cursor, limit)
        return poly_svc.list_references(
            db, actor, target_type, target_id, cursor, limit,
            project_id=_target_scope(project_id, (target_type,)),
        )

    @mcp.tool(name="ref.delete")
    @sessioned
    def ref_delete(id: str) -> dict:
        """删除引用。"""
        db, actor = dbc()
        poly_svc.delete_reference(db, actor, _parse_uuid(id, "id"))
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
        project, role = project_svc.get_project(db, actor, _parse_uuid(id, "id"))
        return {"id": str(project.id), "name": project.name, "my_role": role}

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

    # ---------- search.* ----------
    @mcp.tool(name="search.query")
    @sessioned
    def search_query(
        query: str,
        domains: list[str] | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> dict:
        """跨我有权限的项目搜索(query 关键词)。
        可按 requirement/task/document 过滤，使用 next_cursor 继续读取。"""
        db, actor = dbc()
        return search_svc.search(db, actor, query, domains, cursor=cursor, limit=limit)

    # ---------- attachment.* ----------
    @mcp.tool(name="attachment.upload")
    @sessioned
    def attachment_upload(project_id: str, target_type: str, target_id: str, file_name: str, data: str) -> dict:
        """上传附件挂到实体(data 为文件内容的 base64 字符串);单文件 20MB、项目配额 2GB。"""
        import base64

        db, actor = dbc()
        try:
            payload = base64.b64decode(data, validate=True)
        except (ValueError, TypeError) as exc:
            raise ToolError("invalid_request: data 必须是合法 base64") from exc
        a = attachment_svc.upload(
            db, actor, _require_scope(project_id), target_type, target_id, file_name, payload
        )
        return attachment_svc._attachment_dict(db, a)

    @mcp.tool(name="attachment.download")
    @sessioned
    def attachment_download(attachment_id: str) -> dict:
        """下载附件,返回 base64 内容与文件名。"""
        db, actor = dbc()
        file_name, data, _ = attachment_svc.download(db, actor, _parse_uuid(attachment_id, "attachment_id"))
        import base64

        return {"file_name": file_name, "content": base64.b64encode(data).decode(), "size": len(data)}
