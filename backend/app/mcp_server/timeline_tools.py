"""MCP adapters for requirement timelines and scoped identity discovery."""

from datetime import datetime
from typing import Any, Literal

from mcp.types import ToolAnnotations
from pydantic import BaseModel, StrictInt
from sqlalchemy.orm import Session

from ..errors import invalid_request
from ..v2 import project_completion, timeline as service
from ..v2.resource_refs import ResourceKind, ResourceRef, parse_uuid
from .tools import dbc, sessioned

_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_WITHDRAW = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)

EntryKind = Literal["manual", "system"]


class ReplySummary(BaseModel):
    entry_id: str
    actor_id: str | None
    kind: EntryKind
    withdrawn: bool
    body_preview: str | None
    event_type: str | None


class Entry(BaseModel):
    id: str
    project_id: str
    requirement_id: str
    kind: EntryKind
    actor_id: str | None
    actor_name: str | None
    actor_is_agent: bool
    occurred_at: datetime
    source_task: str | None
    reply_to: ReplySummary | None
    version: int | None
    revised: bool
    withdrawn: bool
    event_type: str | None
    event_data: dict[str, Any] | None


class EntryPreview(Entry):
    body_preview: str | None


class EntryDetail(Entry):
    body: str | None


class EntryContext(BaseModel):
    anchor_id: str
    items: list[EntryPreview]


class Revision(BaseModel):
    version: int
    kind: Literal["create", "revise", "withdraw"]
    actor_id: str | None
    created_at: datetime
    reason: str | None
    body: str | None = None


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


class Receipt(BaseModel):
    entry_id: str
    version: int
    warnings: list[str]


class Candidate(BaseModel):
    id: str
    label: str
    kind: Literal["member", "agent", "wiki", "requirement"]
    href: str
    detail: str


class Candidates(BaseModel):
    items: list[Candidate]


def _scope(project_id: str, requirement_id: str) -> ResourceRef:
    return ResourceRef(parse_uuid(project_id, "project_id"), ResourceKind.REQUIREMENT, requirement_id)


def _receipt(db: Session, result: dict) -> Receipt:
    receipt = Receipt.model_validate(result)
    db.commit()
    return receipt


def register_timeline_tools(mcp) -> None:
    @mcp.tool(name="timeline.list", annotations=_READ)
    @sessioned
    def list_entries(project_id: str, requirement_id: str, cursor: str | None = None, limit: StrictInt = 20,
                     kind: EntryKind | None = None, actor_id: str | None = None, source_task: str | None = None,
                     keyword: str | None = None, from_at: datetime | None = None,
                     to_at: datetime | None = None) -> Page[EntryPreview]:
        """按需求读取时间轴预览，由新到旧。可按类型、作者、来源任务、关键词和含时区时间筛选。"""
        db, actor = dbc()
        result = service.list_entries(
            db, actor, _scope(project_id, requirement_id), cursor=cursor, limit=limit, kind=kind,
            actor_id=parse_uuid(actor_id, "actor_id") if actor_id is not None else None,
            source_task=source_task, keyword=keyword, from_at=from_at, to_at=to_at,
        )
        return Page[EntryPreview].model_validate(result)

    @mcp.tool(name="timeline.get", annotations=_READ)
    @sessioned
    def get_entry(project_id: str, requirement_id: str, entry_id: str) -> EntryDetail:
        """读取一条记录的当前内容。已撤回记录保留身份和撤回标记，旧正文走修订历史。"""
        db, actor = dbc()
        return EntryDetail.model_validate(service.get_entry(db, actor, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id")))

    @mcp.tool(name="timeline.context", annotations=_READ)
    @sessioned
    def get_context(project_id: str, requirement_id: str, entry_id: str, radius: StrictInt = 10) -> EntryContext:
        """从记录深链定位并查看相邻预览，每侧最多 49 条。"""
        db, actor = dbc()
        return EntryContext.model_validate(service.get_context(
            db, actor, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"), radius=radius,
        ))

    @mcp.tool(name="timeline.revisions", annotations=_READ)
    @sessioned
    def list_revisions(project_id: str, requirement_id: str, entry_id: str, cursor: str | None = None,
                       limit: StrictInt = 20, include_body: bool = False) -> Page[Revision]:
        """分页查看修订历史。默认只返回修订信息；需要旧正文时传 include_body=true 且 limit 不超过 5。"""
        if include_body and limit > 5:
            raise invalid_request("读取历史正文时每页最多 5 条修订")
        db, actor = dbc()
        result = service.list_revisions(
            db, actor, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"), cursor=cursor, limit=limit,
        )
        if not include_body:
            for row in result["items"]:
                row.pop("body")
        return Page[Revision].model_validate(result)

    @mcp.tool(name="timeline.append", annotations=_WRITE)
    @sessioned
    def append_entry(project_id: str, requirement_id: str, request_id: str, body: str,
                     source_task: str | None = None, reply_to: str | None = None) -> Receipt:
        """追加人工 Markdown 或回复同需求记录。用同一个 request_id 安全重试。"""
        db, actor = dbc()
        return _receipt(db, service.append_entry(
            db, actor, _scope(project_id, requirement_id), request_id=parse_uuid(request_id, "request_id"),
            body=body, source_task=source_task, reply_to=parse_uuid(reply_to, "reply_to") if reply_to is not None else None,
        ))

    @mcp.tool(name="timeline.revise", annotations=_WRITE)
    @sessioned
    def revise_entry(project_id: str, requirement_id: str, entry_id: str, request_id: str,
                     expected_version: StrictInt, body: str, reason: str | None = None) -> Receipt:
        """按预期版本追加正文修订，保留原文。管理他人记录需填原因。"""
        db, actor = dbc()
        return _receipt(db, service.revise_entry(
            db, actor, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"),
            request_id=parse_uuid(request_id, "request_id"), expected_version=expected_version, body=body, reason=reason,
        ))

    @mcp.tool(name="timeline.withdraw", annotations=_WITHDRAW)
    @sessioned
    def withdraw_entry(project_id: str, requirement_id: str, entry_id: str, request_id: str,
                       expected_version: StrictInt, reason: str | None = None) -> Receipt:
        """按预期版本撤回人工记录并留痕。管理他人记录需填原因。"""
        db, actor = dbc()
        return _receipt(db, service.withdraw_entry(
            db, actor, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"),
            request_id=parse_uuid(request_id, "request_id"), expected_version=expected_version, reason=reason,
        ))

    @mcp.tool(name="project.candidates", annotations=_READ)
    @sessioned
    def candidates(project_id: str, mode: Literal["people", "reference"], query: str = "") -> Candidates:
        """在项目内按名称或编号发现可见成员、附属 Agent、需求或 Wiki，最多返回 20 个匹配候选。"""
        if len(query) > 200 or "\x00" in query:
            raise invalid_request("query 最多包含 200 个有效字符")
        db, actor = dbc()
        items = project_completion.completion_candidates(db, actor, parse_uuid(project_id, "project_id"), mode, query)
        return Candidates.model_validate({"items": items})

    @mcp.tool(name="project.person", annotations=_READ)
    @sessioned
    def person(project_id: str, person_id: str) -> Candidate:
        """按项目读取有权限查看的成员或附属 Agent 资料。"""
        db, actor = dbc()
        return Candidate.model_validate(project_completion.get_person(
            db, actor, parse_uuid(project_id, "project_id"), parse_uuid(person_id, "person_id"),
        ))
