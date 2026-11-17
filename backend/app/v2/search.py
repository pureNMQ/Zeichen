"""Project search with one independently pageable read model per resource domain."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..errors import invalid_request, permission_denied
from ..models import Requirement, Task, User
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..services.permissions import get_accessible_project
from .file_models import ProjectFile
from .files import file_summary
from .page_cursor import as_utc, decode_position, decode_time_position, encode_position, scope_key
from .resource_refs import ResourceKind, ResourceRef, parse_uuid
from .timeline_models import TimelineEntry, TimelineRevision
from .wiki import visible_wiki_codes
from .wiki_models import Wiki


class SearchDomain(StrEnum):
    REQUIREMENT = "requirement"
    TIMELINE = "timeline"
    WIKI = "wiki"
    FILE = "file"


class SearchItem(BaseModel):
    id: str
    project_id: UUID
    domain: SearchDomain
    title: str
    href: str
    snippet: str
    requirement_id: str | None = None
    status: str | None = None
    task_count: int | None = None
    done_task_count: int | None = None
    media_type: str | None = None
    size: int | None = None
    preview_href: str | None = None
    download_href: str | None = None


class SearchPage(BaseModel):
    items: list[SearchItem]
    next_cursor: str | None


class SearchResult(BaseModel):
    domains: dict[SearchDomain, SearchPage]


def _query_terms(query: str) -> tuple[str, ...]:
    query = query.strip()
    if not query or len(query) > 256 or "\x00" in query:
        raise invalid_request("search query 须为 1 至 256 个有效字符")
    terms = tuple(dict.fromkeys(query.split()))
    if len(terms) > 16:
        raise invalid_request("一次最多检索 16 个关键词")
    return terms


def _matches(terms: tuple[str, ...], *columns):
    return and_(*(or_(*(column.icontains(term, autoescape=True) for column in columns)) for term in terms))


def _source_span(text: str, folded: str, start: int, end: int) -> tuple[int, int]:
    if len(text) == len(folded):
        return start, end
    actual_start, offset = 0, 0
    for i, char in enumerate(text):
        offset += len(char.casefold())
        if offset <= start:
            actual_start = i + 1
        if offset >= end:
            return actual_start, i + 1
    return actual_start, len(text)


def _snippet(terms: tuple[str, ...], *fields: str | None) -> str:
    for field in fields:
        if not field:
            continue
        source = " ".join(field.split())
        folded = source.casefold()
        hits = []
        for term in terms:
            key = term.casefold()
            match = folded.find(key)
            if match >= 0:
                hits.append((match, match + len(key)))
        if not hits:
            continue
        hit_start, hit_end = _source_span(source, folded, *min(hits))
        start = max(0, hit_start - 48)
        end = min(len(source), hit_end + 72)
        return ("…" if start else "") + source[start:end] + ("…" if end < len(source) else "")
    return ""


def _identifier_position(scope: str, cursor: str | None, kind: ResourceKind, project_id: UUID) -> str | None:
    value = decode_position(scope, cursor)
    if value is None:
        return None
    if len(value) != 1 or not isinstance(value[0], str):
        raise invalid_request("检索游标格式无效")
    return ResourceRef(project_id, kind, value[0]).identifier


def _shortcode_results(db: Session, statement, column, *, kind: ResourceKind,
                       project_id: UUID, scope: str, cursor: str | None, limit: int):
    after = _identifier_position(scope, cursor, kind, project_id)
    if after is not None:
        statement = statement.where(column > after)
    rows = list(db.execute(statement.order_by(column).limit(limit + 1)))
    return rows[:limit], encode_position(scope, [rows[limit - 1].code]) if len(rows) > limit else None


def _requirements(db: Session, project_id: UUID, terms: tuple[str, ...], scope: str,
                  cursor: str | None, limit: int) -> SearchPage:
    req = Requirement
    statement = select(req.code, req.title, req.description, req.status).where(
        req.project_id == project_id, req.deleted_at.is_(None), _matches(terms, req.code, req.title, req.description),
    )
    rows, next_cursor = _shortcode_results(db, statement, req.code, kind=ResourceKind.REQUIREMENT,
                                           project_id=project_id, scope=scope, cursor=cursor, limit=limit)
    overview = {}
    if rows:
        counts = db.execute(select(Task.requirement_id, func.count(), func.count().filter(Task.status == "done")).where(
            Task.project_id == project_id, Task.deleted_at.is_(None), Task.requirement_id.in_([row.code for row in rows]),
        ).group_by(Task.requirement_id))
        overview = {code: (count, done) for code, count, done in counts}
    return SearchPage(items=[SearchItem(
        id=row.code, project_id=project_id, domain=SearchDomain.REQUIREMENT, title=row.title, status=row.status,
        href=ResourceRef(project_id, ResourceKind.REQUIREMENT, row.code).path,
        snippet=_snippet(terms, row.description, row.title, row.code),
        task_count=overview.get(row.code, (0, 0))[0], done_task_count=overview.get(row.code, (0, 0))[1],
    ) for row in rows], next_cursor=next_cursor)


def _timeline(db: Session, project_id: UUID, terms: tuple[str, ...], scope: str,
              cursor: str | None, limit: int) -> SearchPage:
    entry, revision, requirement = TimelineEntry, TimelineRevision, Requirement
    statement = select(entry.id, entry.requirement_code, entry.occurred_at, requirement.title, revision.body).select_from(entry).join(
        revision, and_(revision.project_id == entry.project_id, revision.requirement_code == entry.requirement_code,
                       revision.entry_id == entry.id, revision.version == entry.latest_version),
    ).join(requirement, and_(requirement.project_id == entry.project_id, requirement.code == entry.requirement_code)).where(
        entry.project_id == project_id, requirement.deleted_at.is_(None), entry.kind == "manual",
        revision.kind != "withdraw", _matches(terms, revision.body),
    )
    position = decode_time_position(scope, cursor)
    if position is not None:
        cutoff, target_id = position
        statement = statement.where(or_(entry.occurred_at < cutoff, and_(entry.occurred_at == cutoff, entry.id < target_id)))
    rows = list(db.execute(statement.order_by(entry.occurred_at.desc(), entry.id.desc()).limit(limit + 1)))
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_position(scope, [as_utc(last.occurred_at).isoformat(), str(last.id)])
    return SearchPage(items=[SearchItem(
        id=str(row.id), project_id=project_id, domain=SearchDomain.TIMELINE, title=row.title, requirement_id=row.requirement_code,
        href=f"{ResourceRef(project_id, ResourceKind.REQUIREMENT, row.requirement_code).path}#timeline-{row.id}",
        snippet=_snippet(terms, row.body),
    ) for row in rows[:limit]], next_cursor=next_cursor)


def _wiki(db: Session, project_id: UUID, terms: tuple[str, ...], scope: str, cursor: str | None, limit: int) -> SearchPage:
    statement = select(Wiki.code, Wiki.title, Wiki.summary, Wiki.body).where(
        Wiki.project_id == project_id, Wiki.code.in_(visible_wiki_codes(project_id)),
        _matches(terms, Wiki.title, Wiki.summary, Wiki.body),
    )
    rows, next_cursor = _shortcode_results(db, statement, Wiki.code, kind=ResourceKind.WIKI,
                                           project_id=project_id, scope=scope, cursor=cursor, limit=limit)
    return SearchPage(items=[SearchItem(
        id=row.code, project_id=project_id, domain=SearchDomain.WIKI, title=row.title,
        href=ResourceRef(project_id, ResourceKind.WIKI, row.code).path, snippet=_snippet(terms, row.body, row.summary, row.title),
    ) for row in rows], next_cursor=next_cursor)


def _files(db: Session, project_id: UUID, terms: tuple[str, ...], scope: str, cursor: str | None, limit: int) -> SearchPage:
    statement = select(ProjectFile).where(
        ProjectFile.project_id == project_id, ProjectFile.deleted_at.is_(None), _matches(terms, ProjectFile.name, ProjectFile.media_type),
    )
    after = _identifier_position(scope, cursor, ResourceKind.FILE, project_id)
    if after is not None:
        statement = statement.where(ProjectFile.id > parse_uuid(after, "cursor.id"))
    rows = list(db.scalars(statement.order_by(ProjectFile.id).limit(limit + 1)))
    return SearchPage(items=[SearchItem(
        domain=SearchDomain.FILE, title=row.name, snippet=_snippet(terms, row.name, row.media_type), **file_summary(row),
    ) for row in rows[:limit]], next_cursor=encode_position(scope, [str(rows[limit - 1].id)]) if len(rows) > limit else None)


_SEARCH = {SearchDomain.REQUIREMENT: _requirements, SearchDomain.TIMELINE: _timeline, SearchDomain.WIKI: _wiki, SearchDomain.FILE: _files}


def search_project(
    db: Session, actor: User, project_id: UUID, *, query: str, domains: list[SearchDomain] | None = None,
    cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
) -> SearchResult:
    if actor.deleted_at is not None:
        raise permission_denied("账号已停用")
    get_accessible_project(db, actor.id, project_id)
    terms = _query_terms(query)
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise invalid_request(f"每个域须为 1 至 {MAX_PAGE_SIZE} 个结果")
    try:
        requested = list(dict.fromkeys(SearchDomain(domain) for domain in domains)) if domains is not None else list(SearchDomain)
    except ValueError:
        raise invalid_request("检索域须为 requirement、timeline、wiki 或 file") from None
    if not requested or (cursor is not None and len(requested) != 1):
        raise invalid_request("续页时通过 domains 明确选择一个检索域")
    return SearchResult(domains={
        domain: _SEARCH[domain](db, project_id, terms, scope_key("search.v2", str(actor.id), str(project_id), domain, terms, limit), cursor, limit)
        for domain in requested
    })
