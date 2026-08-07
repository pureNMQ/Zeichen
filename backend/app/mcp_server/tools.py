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
from ..services import documents as document_svc
from ..services import code_reference as code_svc
from ..services import polymorphic as poly_svc
from ..services import requirements as req_svc
from ..services import tasks as task_svc
from ..services import memory as memory_svc
from ..services import memory_improve_jobs as improve_job_svc
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


def _req_id(requirement_id: str | None) -> uuid.UUID | None:
    return uuid.UUID(requirement_id) if requirement_id else None


def _optional_uuid(value: str | None, field_name: str) -> uuid.UUID | None:
    """Parse an optional MCP UUID while preserving the established empty=root semantics."""
    if value is None or value == "":
        return None
    try:
        return uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ToolError(f"invalid_request: {field_name} 必须是合法 UUID") from None


def _register_all(mcp) -> None:
    # ---------- memory.* ----------
    @mcp.tool(name="memory.remember")
    @sessioned
    def memory_remember(project_id: str, session_id: str, content: str, anchor: dict | None = None) -> dict:
        """向当前项目共享记忆写入会话内容；session_id 为 agent 自己的业务会话 ID。"""
        db, actor = dbc()
        return {"result": memory_svc.remember(db, actor, uuid.UUID(project_id), session_id, content, anchor)}

    @mcp.tool(name="memory.recall")
    @sessioned
    def memory_recall(project_id: str, query: str, session_id: str | None = None) -> dict:
        """在当前项目 Dataset 内检索共享记忆。"""
        db, actor = dbc()
        return {"result": memory_svc.recall(db, actor, uuid.UUID(project_id), query, session_id)}

    @mcp.tool(name="memory.improve")
    @sessioned
    def memory_improve(project_id: str, session_id: str) -> dict:
        """提交当前 agent 会话的异步蒸馏，立即返回可轮询的 job；不等待 Cognee 完成。"""
        db, actor = dbc()
        return {"job": improve_job_svc.submit(db, actor, uuid.UUID(project_id), actor.id, session_id)}

    @mcp.tool(name="memory.improve_status")
    @sessioned
    def memory_improve_status(project_id: str, job_id: str) -> dict:
        """查询异步会话蒸馏任务；仅 status=completed 表示已成功写入长期记忆。"""
        db, actor = dbc()
        return {"job": improve_job_svc.get(db, actor, uuid.UUID(project_id), uuid.UUID(job_id))}

    @mcp.tool(name="memory.forget")
    @sessioned
    def memory_forget(project_id: str, data_id: str) -> dict:
        """删除当前项目 Dataset 内的一条记忆。"""
        db, actor = dbc()
        return {"result": memory_svc.forget(db, actor, uuid.UUID(project_id), data_id)}

    @mcp.tool(name="memory.list")
    @sessioned
    def memory_list(project_id: str, source_id: str | None = None) -> dict:
        """列出当前项目的共享记忆，可按创建来源过滤。"""
        db, actor = dbc()
        return memory_svc.list_memory(db, actor, uuid.UUID(project_id), uuid.UUID(source_id) if source_id else None)

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
        requirement_id: str | None = _UNSET,
    ) -> dict:
        """更新任务元数据；省略 requirement_id 保留关联，传 null 或空字符串解除关联。"""
        db, actor = dbc()
        if requirement_id is _UNSET:
            t = task_svc.update_task(db, actor, uuid.UUID(id), title, description)
        else:
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

    # ---------- docs.wiki.* / docs.glossary.* ----------
    def _doc_create(project_id: str, title: str, module: str, content: str, metadata: dict | None, parent_id: str | None = None, directory_id: str | None = None) -> dict:
        db, actor = dbc()
        document = document_svc.create_document(
            db, actor, uuid.UUID(project_id), title, module, content, metadata,
            _optional_uuid(parent_id, "parent_id"), _optional_uuid(directory_id, "directory_id"),
        )
        return document_svc._document_dict(db, document)

    def _doc_get(id: str, module: str) -> dict:
        db, actor = dbc()
        return document_svc._document_dict(db, document_svc.get_document(db, actor, uuid.UUID(id), module))

    def _doc_children(project_id: str, module: str, parent_id: str | None, cursor: str | None, limit: int | None) -> dict:
        db, actor = dbc()
        cursor, limit = _paged({"project_id": project_id, "module": module, "parent_id": parent_id}, cursor, limit)
        return document_svc.list_module_children(db, actor, uuid.UUID(project_id), module, _optional_uuid(parent_id, "parent_id"), cursor, limit)

    def _doc_update(id: str, module: str, title: str | None, content: str | None, metadata: dict | None = None) -> dict:
        db, actor = dbc()
        document = document_svc.get_document(db, actor, uuid.UUID(id), module)
        saved, warning = document_svc.update_document(
            db, actor, document.id, title, content, metadata if metadata is not None else document_svc._UNSET,
        )
        return document_svc._document_dict(db, saved, warning)

    def _doc_move(id: str, module: str, parent_id: str = "", directory_id: str = "") -> dict:
        db, actor = dbc()
        document = document_svc.get_document(db, actor, uuid.UUID(id), module)
        moved = document_svc.move_document(
            db, actor, document.id, _optional_uuid(parent_id, "parent_id"), _optional_uuid(directory_id, "directory_id")
        )
        return document_svc._document_dict(db, moved)

    def _doc_delete(id: str, module: str) -> dict:
        db, actor = dbc()
        document = document_svc.get_document(db, actor, uuid.UUID(id), module)
        impact = document_svc.delete_impact_document(db, actor, document.id)
        document_svc.delete_document(db, actor, document.id)
        return {"deleted": True, "id": id, "impact": impact}

    def _doc_restore(id: str, module: str) -> dict:
        db, actor = dbc()
        document = document_svc._visible_document(db, actor, uuid.UUID(id), include_deleted=True)
        if document.doc_type != module:
            raise ToolError("not_found: 文档不存在")
        return document_svc._document_dict(db, document_svc.restore_document(db, actor, document.id))

    def _doc_path(project_id: str, module: str, node_kind: str, id: str) -> dict:
        db, actor = dbc()
        return document_svc.ancestor_path(db, actor, uuid.UUID(project_id), module, node_kind, uuid.UUID(id))

    def _doc_deleted(project_id: str, module: str, cursor: str | None, limit: int | None) -> dict:
        db, actor = dbc()
        cursor, limit = _paged({"project_id": project_id, "module": module, "deleted": True}, cursor, limit)
        return document_svc.list_deleted_nodes(db, actor, uuid.UUID(project_id), module, cursor, limit)

    @mcp.tool(name="docs.wiki.create")
    @sessioned
    def docs_wiki_create(project_id: str, title: str, content: str = "", parent_id: str | None = None) -> dict:
        """创建根 Wiki 或指定父 Wiki 下的子 Wiki。"""
        return _doc_create(project_id, title, "wiki", content, {}, parent_id=parent_id)

    @mcp.tool(name="docs.wiki.get")
    @sessioned
    def docs_wiki_get(id: str) -> dict:
        return _doc_get(id, "wiki")

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
    def docs_wiki_update(id: str, title: str | None = None, content: str | None = None) -> dict:
        return _doc_update(id, "wiki", title, content)

    @mcp.tool(name="docs.wiki.move")
    @sessioned
    def docs_wiki_move(id: str, parent_id: str = "") -> dict:
        """移动 Wiki；省略 parent_id 或传空字符串移动到根节点。"""
        return _doc_move(id, "wiki", parent_id=parent_id)

    @mcp.tool(name="docs.wiki.versions")
    @sessioned
    def docs_wiki_versions(id: str) -> dict:
        db, actor = dbc()
        return {"items": document_svc.list_versions(db, actor, uuid.UUID(id), "wiki")}

    @mcp.tool(name="docs.wiki.rollback")
    @sessioned
    def docs_wiki_rollback(id: str, version_no: int) -> dict:
        db, actor = dbc()
        return document_svc._document_dict(db, document_svc.rollback_document(db, actor, uuid.UUID(id), version_no, "wiki"))

    @mcp.tool(name="docs.wiki.delete")
    @sessioned
    def docs_wiki_delete(id: str) -> dict:
        return _doc_delete(id, "wiki")

    @mcp.tool(name="docs.wiki.restore")
    @sessioned
    def docs_wiki_restore(id: str) -> dict:
        return _doc_restore(id, "wiki")

    def _register_directory_tools(mcp, module: str) -> None:
        @mcp.tool(name=f"docs.{module}.directory_create")
        @sessioned
        def directory_create(project_id: str, name: str, parent_id: str | None = None) -> dict:
            db, actor = dbc()
            directory = document_svc.create_directory(db, actor, uuid.UUID(project_id), module, name, _optional_uuid(parent_id, "parent_id"))
            return document_svc._directory_dict(db, directory)

        @mcp.tool(name=f"docs.{module}.directory_move")
        @sessioned
        def directory_move(id: str, parent_id: str = "") -> dict:
            """移动目录；省略 parent_id 或传空字符串移动到根节点。"""
            db, actor = dbc()
            directory = document_svc.get_directory(db, actor, uuid.UUID(id), module)
            moved = document_svc.move_directory(db, actor, directory.id, _optional_uuid(parent_id, "parent_id"))
            return document_svc._directory_dict(db, moved)

        @mcp.tool(name=f"docs.{module}.directory_rename")
        @sessioned
        def directory_rename(id: str, name: str) -> dict:
            db, actor = dbc()
            directory = document_svc.get_directory(db, actor, uuid.UUID(id), module)
            return document_svc._directory_dict(db, document_svc.rename_directory(db, actor, directory.id, name))

        @mcp.tool(name=f"docs.{module}.directory_delete")
        @sessioned
        def directory_delete(id: str) -> dict:
            db, actor = dbc()
            directory = document_svc.get_directory(db, actor, uuid.UUID(id), module)
            impact = document_svc.delete_impact_directory(db, actor, directory.id)
            document_svc.delete_directory(db, actor, directory.id)
            return {"deleted": True, "id": id, "impact": impact}

        @mcp.tool(name=f"docs.{module}.directory_restore")
        @sessioned
        def directory_restore(id: str) -> dict:
            db, actor = dbc()
            directory = document_svc._get_directory_raw(db, uuid.UUID(id))
            if directory.module_type != module:
                raise ToolError("not_found: 目录不存在")
            return document_svc._directory_dict(db, document_svc.restore_directory(db, actor, directory.id))

    @mcp.tool(name="docs.glossary.create")
    @sessioned
    def docs_glossary_create(project_id: str, title: str, content: str = "", directory_id: str | None = None) -> dict:
        return _doc_create(project_id, title, "glossary", content, {}, directory_id=directory_id)

    @mcp.tool(name="docs.glossary.get")
    @sessioned
    def docs_glossary_get(project_id: str | None = None, title: str | None = None, id: str | None = None) -> dict:
        db, actor = dbc()
        if id:
            return _doc_get(id, "glossary")
        if not project_id or not title:
            raise ToolError("invalid_request: 需要 id 或 project_id + title")
        return document_svc._document_dict(db, document_svc.get_glossary_term(db, actor, uuid.UUID(project_id), title))

    @mcp.tool(name="docs.glossary.children")
    @sessioned
    def docs_glossary_children(project_id: str, parent_id: str | None = None, cursor: str | None = None, limit: int | None = None) -> dict:
        return _doc_children(project_id, "glossary", parent_id, cursor, limit)

    @mcp.tool(name="docs.glossary.list")
    @sessioned
    def docs_glossary_list(project_id: str, cursor: str | None = None, limit: int | None = None) -> dict:
        return _doc_children(project_id, "glossary", None, cursor, limit)

    @mcp.tool(name="docs.glossary.ancestors")
    @sessioned
    def docs_glossary_ancestors(project_id: str, id: str, node_kind: str = "document") -> dict:
        return _doc_path(project_id, "glossary", node_kind, id)

    @mcp.tool(name="docs.glossary.update")
    @sessioned
    def docs_glossary_update(id: str, title: str | None = None, content: str | None = None) -> dict:
        return _doc_update(id, "glossary", title, content)

    @mcp.tool(name="docs.glossary.move")
    @sessioned
    def docs_glossary_move(id: str, directory_id: str = "") -> dict:
        """移动术语；省略 directory_id 或传空字符串移动到根节点。"""
        return _doc_move(id, "glossary", directory_id=directory_id)

    @mcp.tool(name="docs.glossary.deleted")
    @sessioned
    def docs_glossary_deleted(project_id: str, cursor: str | None = None, limit: int | None = None) -> dict:
        return _doc_deleted(project_id, "glossary", cursor, limit)

    @mcp.tool(name="docs.glossary.delete")
    @sessioned
    def docs_glossary_delete(id: str) -> dict:
        return _doc_delete(id, "glossary")

    @mcp.tool(name="docs.glossary.restore")
    @sessioned
    def docs_glossary_restore(id: str) -> dict:
        return _doc_restore(id, "glossary")

    _register_directory_tools(mcp, "glossary")

    # ---------- docs.code.* ----------
    @mcp.tool(name="docs.code.library_create")
    @sessioned
    def docs_code_library_create(project_id: str, name: str, language: str, package: str, version: str | None = None) -> dict:
        db, actor = dbc()
        return code_svc._library_dict(code_svc.create_library(db, actor, uuid.UUID(project_id), name, language, package, version))

    @mcp.tool(name="docs.code.library_list")
    @sessioned
    def docs_code_library_list(project_id: str) -> dict:
        db, actor = dbc()
        return {"items": code_svc.list_libraries(db, actor, uuid.UUID(project_id))}

    @mcp.tool(name="docs.code.search")
    @sessioned
    def docs_code_search(project_id: str, query: str | None = None, library_id: str | None = None, kind: str | None = None) -> dict:
        db, actor = dbc()
        return {"items": code_svc.search_symbols(db, actor, uuid.UUID(project_id), query, uuid.UUID(library_id) if library_id else None, kind)}

    @mcp.tool(name="docs.code.get")
    @sessioned
    def docs_code_get(id: str) -> dict:
        db, actor = dbc()
        return code_svc.get_symbol(db, actor, uuid.UUID(id))

    @mcp.tool(name="docs.code.create")
    @sessioned
    def docs_code_create(library_id: str, symbol: dict) -> dict:
        db, actor = dbc()
        return code_svc._symbol_dict(code_svc.create_symbol(db, actor, uuid.UUID(library_id), symbol))

    @mcp.tool(name="docs.code.update")
    @sessioned
    def docs_code_update(id: str, expected_revision: int, patch: dict) -> dict:
        db, actor = dbc()
        return code_svc._symbol_dict(code_svc.update_symbol(db, actor, uuid.UUID(id), expected_revision, patch))

    @mcp.tool(name="docs.code.members")
    @sessioned
    def docs_code_members(symbol_id: str) -> dict:
        """列出一个类型符号的直接成员；symbol_id 不是 library_id。"""
        db, actor = dbc()
        return {"items": code_svc.list_members(db, actor, uuid.UUID(symbol_id))}

    @mcp.tool(name="docs.code.versions")
    @sessioned
    def docs_code_versions(id: str) -> dict:
        db, actor = dbc()
        return {"items": code_svc.list_versions(db, actor, uuid.UUID(id))}

    @mcp.tool(name="docs.code.rollback")
    @sessioned
    def docs_code_rollback(id: str, revision: int, expected_revision: int) -> dict:
        db, actor = dbc()
        return code_svc._symbol_dict(code_svc.rollback_symbol(db, actor, uuid.UUID(id), revision, expected_revision))

    @mcp.tool(name="docs.code.delete")
    @sessioned
    def docs_code_delete(id: str) -> dict:
        db, actor = dbc()
        code_svc.delete_symbol(db, actor, uuid.UUID(id))
        return {"deleted": True, "id": id}

    @mcp.tool(name="docs.code.restore")
    @sessioned
    def docs_code_restore(id: str) -> dict:
        db, actor = dbc()
        return code_svc._symbol_dict(code_svc.restore_symbol(db, actor, uuid.UUID(id)))

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
