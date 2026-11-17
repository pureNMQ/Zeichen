"""Structured Wiki tools kept independent of the legacy docs.wiki registry."""

from datetime import datetime
from uuid import UUID

from mcp.types import ToolAnnotations
from pydantic import BaseModel, StrictInt

from ..errors import conflict, invalid_request
from ..services.permissions import require_project_role
from ..v2 import wiki as service
from ..v2.resource_refs import parse_uuid
from . import wiki_reads as reads
from .tools import dbc, sessioned

_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
_CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)
_DELETE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


class WikiReceipt(BaseModel):
    project_id: UUID
    id: str
    version: int


class DeleteImpact(WikiReceipt):
    affected_count: int
    sample: list[str]


class DeletedWiki(WikiReceipt):
    deleted: bool


class RestoredWiki(WikiReceipt):
    restored: bool


class HistoricalRead(reads.WikiRead):
    summary: str | None
    category: str | None
    tags: list[str]
    created_at: datetime
    created_by: UUID | None


def register_wiki_tools(mcp) -> None:
    @mcp.tool(name="wiki.list", annotations=_READ)
    @sessioned
    def list_wiki(project_id: str, query: str = "", parent_id: str | None = None,
                  cursor: str | None = None, limit: StrictInt = 20) -> reads.Page[reads.WikiSummary]:
        """新版有效 Wiki 摘要；省略父编号浏览全项目，传父编号只列直接子页。用 next_cursor 续页。"""
        db, actor = dbc()
        return reads.list_wiki(db, actor.id, parse_uuid(project_id, "project_id"), query=query, parent_id=parent_id,
                               cursor=cursor, limit=limit)

    @mcp.tool(name="wiki.get", annotations=_READ)
    @sessioned
    def get_wiki(project_id: str, id: str) -> reads.WikiSummary:
        """读取 Wiki 属性及当前版本号。正文通过 wiki.read 按需读取。"""
        db, actor = dbc()
        return reads.summary(service.read_wiki(db, actor.id, parse_uuid(project_id, "project_id"), id))

    @mcp.tool(name="wiki.read", annotations=_READ)
    @sessioned
    def read_wiki(project_id: str, id: str, mode: reads.ReadMode = "range", start_line: StrictInt | None = None,
                  end_line: StrictInt | None = None) -> reads.WikiRead:
        """读取当前正文。range 为 1 起始的包含范围（最多 200 行及 32 KiB）；outline 返回标题和续读行；full 显式要全文。"""
        db, actor = dbc()
        entry = service.read_wiki(db, actor.id, parse_uuid(project_id, "project_id"), id)
        return reads.body_read(entry, mode=mode, start_line=start_line, end_line=end_line)

    @mcp.tool(name="wiki.create", annotations=_CREATE)
    @sessioned
    def create_wiki(project_id: str, request_id: str, content: service.WikiContent, parent_id: str | None = None) -> WikiReceipt:
        """创建新版 Wiki。相同请求 UUID 和内容重试返回原回执。"""
        db, actor = dbc()
        result = service.create_wiki(db, actor.id, parse_uuid(project_id, "project_id"),
                                     request_id=parse_uuid(request_id, "request_id"), content=content, parent_id=parent_id)
        db.commit()
        return WikiReceipt.model_validate(result)

    @mcp.tool(name="wiki.update", annotations=_WRITE)
    @sessioned
    def update_wiki(project_id: str, id: str, expected_version: StrictInt, patch: service.WikiPatch) -> WikiReceipt:
        """修改结构化属性；省略不变。提供 body 会替换全文，小范围编辑请调用 wiki.edit。"""
        db, actor = dbc()
        result = service.update_wiki(db, actor.id, parse_uuid(project_id, "project_id"), id,
                                     expected_version=expected_version, patch=patch)
        db.commit()
        return WikiReceipt.model_validate(result)

    @mcp.tool(name="wiki.edit", annotations=_WRITE)
    @sessioned
    def edit_wiki(project_id: str, id: str, expected_version: StrictInt, start_line: StrictInt,
                  end_line: StrictInt, replacement: str) -> WikiReceipt:
        """按读取版本替换 1 起始的包含行范围。空正文删除所选行；保留其余正文和相邻换行。"""
        db, actor = dbc()
        scope = parse_uuid(project_id, "project_id")
        require_project_role(db, actor.id, scope)
        if expected_version < 1:
            raise invalid_request("expected_version 必须大于零")
        entry = service.read_wiki(db, actor.id, scope, id)
        if expected_version != entry.version_no:
            raise conflict(f"Wiki 已更新，当前版本为 {entry.version_no}，请重新读取后再保存")
        body = reads.replace_lines(entry.body, start_line, end_line, replacement)
        result = service.update_wiki(db, actor.id, scope, id, expected_version=expected_version, patch=service.WikiPatch(body=body))
        db.commit()
        return WikiReceipt.model_validate(result)

    @mcp.tool(name="wiki.move", annotations=_WRITE)
    @sessioned
    def move_wiki(project_id: str, id: str, parent_id: str | None, expected_version: StrictInt) -> WikiReceipt:
        """按预期版本移动 Wiki；parent_id 显式为 null 时移动到根。"""
        db, actor = dbc()
        result = service.move_wiki(db, actor.id, parse_uuid(project_id, "project_id"), id, parent_id, expected_version)
        db.commit()
        return WikiReceipt.model_validate(result)

    @mcp.tool(name="wiki.versions", annotations=_READ)
    @sessioned
    def list_versions(project_id: str, id: str, cursor: str | None = None, limit: StrictInt = 20) -> reads.Page[reads.VersionSummary]:
        """分页列出版本标题、作者和时间，近期版本在前。使用 next_cursor 续页，正文另取。"""
        db, actor = dbc()
        return reads.version_list(db, actor.id, parse_uuid(project_id, "project_id"), id, limit=limit, cursor=cursor)

    @mcp.tool(name="wiki.read_version", annotations=_READ)
    @sessioned
    def read_version(project_id: str, id: str, version: StrictInt, mode: reads.ReadMode = "range",
                     start_line: StrictInt | None = None, end_line: StrictInt | None = None) -> HistoricalRead:
        """查看指定历史版本的属性及正文。range、outline 与 full 的含义同 wiki.read。"""
        db, actor = dbc()
        entry = service.read_version(db, actor.id, parse_uuid(project_id, "project_id"), id, version)
        payload = reads.body_read(entry, mode=mode, start_line=start_line, end_line=end_line)
        return HistoricalRead(**payload.model_dump(), summary=entry.summary, category=entry.category, tags=entry.tags,
                              created_at=entry.created_at, created_by=entry.created_by)

    @mcp.tool(name="wiki.restore_version", annotations=_WRITE)
    @sessioned
    def restore_version(project_id: str, id: str, expected_version: StrictInt, from_version: StrictInt) -> WikiReceipt:
        """将历史正文和属性恢复为新版本，保留所有旧版本。"""
        db, actor = dbc()
        result = service.restore_wiki_version(db, actor.id, parse_uuid(project_id, "project_id"), id,
                                              expected_version=expected_version, from_version=from_version)
        db.commit()
        return WikiReceipt.model_validate(result)

    @mcp.tool(name="wiki.delete_impact", annotations=_READ)
    @sessioned
    def delete_impact(project_id: str, id: str) -> DeleteImpact:
        """删除前检查受影响的 Wiki 数量，最多示例 50 个短码。"""
        db, actor = dbc()
        return DeleteImpact.model_validate(service.wiki_delete_impact(db, actor.id, parse_uuid(project_id, "project_id"), id))

    @mcp.tool(name="wiki.delete", annotations=_DELETE)
    @sessioned
    def delete_wiki(project_id: str, id: str, confirmed_count: StrictInt) -> DeletedWiki:
        """按 wiki.delete_impact 返回的数量确认删除，将 Wiki 放入回收站。"""
        db, actor = dbc()
        result = service.delete_wiki(db, actor.id, parse_uuid(project_id, "project_id"), id, confirmed_count)
        db.commit()
        return DeletedWiki.model_validate(result)

    @mcp.tool(name="wiki.trash_list", annotations=_READ)
    @sessioned
    def list_trash(project_id: str, query: str = "", cursor: str | None = None,
                   limit: StrictInt = 20) -> reads.Page[reads.TrashedWiki]:
        """按项目查找已进入回收站的 Wiki，返回标题、编号和删除信息。"""
        db, actor = dbc()
        return reads.list_trash(db, actor.id, parse_uuid(project_id, "project_id"), query=query, cursor=cursor, limit=limit)

    @mcp.tool(name="wiki.trash_get", annotations=_READ)
    @sessioned
    def get_trashed_wiki(project_id: str, id: str) -> reads.TrashedWiki:
        """查看指定回收站条目的元信息，无权或未删除时不返回内容。"""
        db, actor = dbc()
        return reads.read_trash(db, actor.id, parse_uuid(project_id, "project_id"), id)

    @mcp.tool(name="wiki.restore", annotations=_WRITE)
    @sessioned
    def restore_wiki(project_id: str, id: str) -> RestoredWiki:
        """恢复已删除的 Wiki，保留原编号和历史；父级仍删除或同名冲突会说明原因。"""
        db, actor = dbc()
        result = service.restore_wiki(db, actor.id, parse_uuid(project_id, "project_id"), id)
        db.commit()
        return RestoredWiki.model_validate(result)
