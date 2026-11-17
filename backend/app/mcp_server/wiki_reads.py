"""Bounded read projections and cursors for the v2 Wiki MCP tools."""

import hashlib
import hmac
import json
import re
from datetime import datetime
from itertools import pairwise
from typing import Literal
from uuid import UUID

from markdown_it import MarkdownIt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from ..config import get_settings
from ..errors import invalid_request, not_found
from ..services.pagination import MAX_PAGE_SIZE
from ..services.permissions import get_accessible_project, require_project_role
from ..v2 import wiki as service
from ..v2.resource_refs import ResourceKind, ResourceRef
from ..v2.wiki_models import Wiki, WikiVersion

ReadMode = Literal["full", "range", "outline"]
MAX_RANGE_LINES = 200
MAX_RANGE_BYTES = 32 * 1024
_MAX_HEADINGS = 100
_MAX_HEADING_TITLE = 240
_SUMMARY_LIMIT = 240
_MARKDOWN = MarkdownIt("commonmark").enable("table")
_SOURCE_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|$)")


class WikiSummary(BaseModel):
    id: str
    project_id: UUID
    parent_id: str | None
    title: str
    summary: str | None
    summary_truncated: bool
    category: str | None
    tags: list[str]
    version: int
    updated_at: datetime


class TrashedWiki(WikiSummary):
    deleted_at: datetime
    deleted_by: UUID | None


class Ancestor(BaseModel):
    id: str
    title: str


class VersionSummary(BaseModel):
    version: int
    title: str
    created_at: datetime
    created_by: UUID | None


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


class Heading(BaseModel):
    line: int
    level: int
    title: str
    title_truncated: bool


class WikiRead(BaseModel):
    id: str
    project_id: UUID
    version: int
    mode: ReadMode
    title: str
    start_line: int | None
    end_line: int | None
    total_lines: int
    next_start_line: int | None
    body: str | None = None
    headings: list[Heading] | None = None


def _parse_cursor(scope: dict, cursor: str | None) -> str | None:
    if cursor is None:
        return None
    anchor, separator, _ = cursor.partition(".")
    if len(cursor) > 100 or not separator or not anchor or not hmac.compare_digest(
        _cursor(scope, anchor).encode(), cursor.encode(),
    ):
        raise invalid_request("Wiki 游标无效或不属于当前查询，请重新读取第一页")
    return anchor


def _cursor(scope: dict, anchor: str) -> str:
    signed = json.dumps(["zeichen/wiki/v2/cursor", scope, anchor], sort_keys=True, separators=(",", ":"))
    signature = hmac.new(get_settings().session_secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"{anchor}.{signature}"


def _limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise invalid_request(f"limit 必须在 1..{MAX_PAGE_SIZE} 之间")


def summary(wiki: Wiki, *, preview: bool = False) -> WikiSummary:
    value = wiki.summary
    truncated = preview and value is not None and len(value) > _SUMMARY_LIMIT
    return WikiSummary(
        id=wiki.code, project_id=wiki.project_id, parent_id=wiki.parent_id, title=wiki.title,
        summary=value[:_SUMMARY_LIMIT] if truncated else value, summary_truncated=truncated,
        category=wiki.category, tags=wiki.tags, version=wiki.version_no, updated_at=wiki.updated_at,
    )


def trashed_summary(wiki: Wiki, *, preview: bool = False) -> TrashedWiki:
    return TrashedWiki(**summary(wiki, preview=preview).model_dump(), deleted_at=wiki.deleted_at, deleted_by=wiki.deleted_by)


def _project_list(db: Session, actor_id: UUID, project_id: UUID, *, query: str, limit: int,
                  cursor: str | None, deleted: bool, parent_id: str | None = None) -> tuple[list[Wiki], str | None]:
    get_accessible_project(db, actor_id, project_id, min_level="editor" if deleted else "viewer")
    _limit(limit)
    query = query.strip()
    if len(query) > 256:
        raise invalid_request("query 最多 256 字")
    if parent_id is not None:
        service.read_wiki(db, actor_id, project_id, parent_id)
    scope = {"mode": "trash" if deleted else "list", "actor": str(actor_id), "project": str(project_id),
             "query": query, "parent": parent_id, "limit": limit}
    anchor = _parse_cursor(scope, cursor)
    statement = select(Wiki).options(load_only(
        Wiki.project_id, Wiki.code, Wiki.parent_id, Wiki.title, Wiki.summary, Wiki.category,
        Wiki.tags, Wiki.version_no, Wiki.updated_at, Wiki.deleted_at, Wiki.deleted_by,
    )).where(Wiki.project_id == project_id)
    if deleted:
        statement = statement.where(Wiki.deleted_at.is_not(None))
    else:
        statement = statement.where(Wiki.code.in_(service.visible_wiki_codes(project_id)))
    if query:
        statement = statement.where(Wiki.title.icontains(query, autoescape=True) | Wiki.code.icontains(query, autoescape=True))
    if parent_id is not None:
        statement = statement.where(Wiki.parent_id == parent_id)
    if anchor is not None:
        statement = statement.where(Wiki.code > anchor)
    entries = list(db.scalars(statement.order_by(Wiki.code).limit(limit + 1)))
    return entries[:limit], _cursor(scope, entries[limit - 1].code) if len(entries) > limit else None


def list_wiki(db: Session, actor_id: UUID, project_id: UUID, *, query: str, parent_id: str | None,
              cursor: str | None, limit: int) -> Page[WikiSummary]:
    entries, next_cursor = _project_list(db, actor_id, project_id, query=query, parent_id=parent_id,
                                         limit=limit, cursor=cursor, deleted=False)
    return Page(items=[summary(entry, preview=True) for entry in entries], next_cursor=next_cursor)


def ancestors(db: Session, actor_id: UUID, project_id: UUID, code: str) -> list[Ancestor]:
    get_accessible_project(db, actor_id, project_id)
    ResourceRef(project_id, ResourceKind.WIKI, code)
    path: list[Ancestor] = []
    seen: set[str] = set()
    node_id = code
    while node_id is not None:
        if node_id in seen:
            raise not_found("Wiki 路径不存在")
        seen.add(node_id)
        node = db.execute(select(Wiki.code, Wiki.parent_id, Wiki.title).where(
            Wiki.project_id == project_id, Wiki.code == node_id, Wiki.deleted_at.is_(None),
        )).one_or_none()
        if node is None:
            raise not_found("Wiki 路径不存在")
        path.append(Ancestor(id=node.code, title=node.title))
        node_id = node.parent_id
    return list(reversed(path))


def list_trash(db: Session, actor_id: UUID, project_id: UUID, *, query: str,
               cursor: str | None, limit: int) -> Page[TrashedWiki]:
    entries, next_cursor = _project_list(db, actor_id, project_id, query=query,
                                         limit=limit, cursor=cursor, deleted=True)
    return Page(items=[trashed_summary(entry, preview=True) for entry in entries], next_cursor=next_cursor)


def read_trash(db: Session, actor_id: UUID, project_id: UUID, code: str) -> TrashedWiki:
    require_project_role(db, actor_id, project_id)
    ResourceRef(project_id, ResourceKind.WIKI, code)
    entry = db.get(Wiki, (project_id, code))
    if entry is None or entry.deleted_at is None:
        raise not_found("已删除的 Wiki 不存在")
    return trashed_summary(entry)


def version_list(db: Session, actor_id: UUID, project_id: UUID, code: str, *, limit: int,
                 cursor: str | None) -> Page[VersionSummary]:
    service.read_wiki(db, actor_id, project_id, code)
    _limit(limit)
    scope = {"mode": "version_list", "actor": str(actor_id), "project": str(project_id), "wiki": code, "limit": limit}
    anchor = _parse_cursor(scope, cursor)
    statement = select(WikiVersion.version_no, WikiVersion.title, WikiVersion.created_at, WikiVersion.created_by).where(
        WikiVersion.project_id == project_id, WikiVersion.wiki_code == code,
    )
    if anchor is not None:
        statement = statement.where(WikiVersion.version_no < int(anchor))
    rows = db.execute(statement.order_by(WikiVersion.version_no.desc()).limit(limit + 1)).all()
    return Page(
        items=[VersionSummary(version=row.version_no, title=row.title, created_at=row.created_at, created_by=row.created_by)
               for row in rows[:limit]],
        next_cursor=_cursor(scope, str(rows[limit - 1].version_no)) if len(rows) > limit else None,
    )


def source_lines(body: str) -> list[str]:
    """The Markdown parser counts CR/LF line breaks; preserve original terminators for edits."""
    return [line.group() for line in _SOURCE_LINE.finditer(body) if line.start() != line.end()]


def _range_end(line_count: int, start: int, end: int | None) -> int:
    if start < 1 or start > line_count or (end is not None and (end < start or end > line_count)):
        raise invalid_request(f"行号须在 1..{line_count}，且结束行不能小于起始行")
    final = end if end is not None else min(line_count, start + MAX_RANGE_LINES - 1)
    if final - start + 1 > MAX_RANGE_LINES:
        raise invalid_request(f"一次最多选择 {MAX_RANGE_LINES} 行")
    return final


def _outline(body: str, start: int) -> tuple[list[Heading], int | None]:
    headings: list[Heading] = []
    tokens = _MARKDOWN.parse(body)
    for token, following in pairwise(tokens):
        if token.type != "heading_open" or token.map is None or following.type != "inline":
            continue
        line = token.map[0] + 1
        if line < start:
            continue
        if len(headings) == _MAX_HEADINGS:
            return headings, line
        title = following.content
        headings.append(Heading(line=line, level=int(token.tag[-1]), title=title[:_MAX_HEADING_TITLE],
                                title_truncated=len(title) > _MAX_HEADING_TITLE))
    return headings, None


def body_read(entry: Wiki | WikiVersion, *, mode: ReadMode, start_line: int | None,
              end_line: int | None) -> WikiRead:
    code = entry.code if isinstance(entry, Wiki) else entry.wiki_code
    body = entry.body
    lines = source_lines(body)
    read = WikiRead(id=code, project_id=entry.project_id, version=entry.version_no, mode=mode,
                    title=entry.title, total_lines=len(lines), start_line=None, end_line=None, next_start_line=None)
    if mode == "full":
        if start_line is not None or end_line is not None:
            raise invalid_request("全文读取不能同时指定行范围")
        return read.model_copy(update={"body": body, "start_line": 1 if lines else None, "end_line": len(lines) or None})
    start = 1 if start_line is None else start_line
    if mode == "outline":
        if end_line is not None or start < 1 or start > max(1, len(lines)):
            raise invalid_request("大纲读取只能指定有效的起始行")
        headings, next_start = _outline(body, start)
        return read.model_copy(update={"headings": headings, "start_line": start if lines else None,
                                       "end_line": (next_start - 1 if next_start else len(lines)) or None,
                                       "next_start_line": next_start})
    if not lines and start == 1 and end_line is None:
        return read.model_copy(update={"body": ""})
    end = _range_end(len(lines), start, end_line)
    selected = "".join(lines[start - 1:end])
    if len(selected.encode()) > MAX_RANGE_BYTES:
        raise invalid_request("选中的正文超过 32 KiB，请缩小范围或显式读取全文")
    return read.model_copy(update={"body": selected, "start_line": start, "end_line": end,
                                   "next_start_line": end + 1 if end < len(lines) else None})


def replace_lines(body: str, start: int, end: int, replacement: str) -> str:
    lines = source_lines(body)
    _range_end(len(lines), start, end)
    if len(replacement.encode()) > MAX_RANGE_BYTES:
        raise invalid_request("替换正文超过 32 KiB，请拆分编辑")
    if replacement and end < len(lines) and not replacement.endswith(("\r", "\n")):
        # Preserve the existing separation from the first unmodified following line.
        original_break = lines[end - 1][len(lines[end - 1].rstrip("\r\n")):]
        replacement += original_break
    return "".join(lines[:start - 1]) + replacement + "".join(lines[end:])
