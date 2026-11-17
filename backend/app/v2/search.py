"""Project search with one independently pageable read model per resource domain."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, true, tuple_
from sqlalchemy.orm import Session

from ..errors import invalid_request, permission_denied
from ..models import Requirement, Task, User
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..services.permissions import get_accessible_project
from .file_models import ProjectFile
from .files import file_summary
from .page_cursor import as_utc, decode_position, decode_time_position, encode_position, scope_key
from .resource_refs import ResourceKind, ResourceRef, parse_uuid
from .search_filters import SearchFilters, file_used_at_predicate, wiki_tag_predicate
from .timeline_models import TimelineEntry, TimelineRevision
from .wiki_models import Wiki, visible_wiki_tree

MAX_SEARCH_PROJECTS = 12


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
    if len(query) > 256 or "\x00" in query:
        raise invalid_request("搜索关键词最多 256 个有效字符")
    terms = tuple(dict.fromkeys(query.split()))
    if len(terms) > 16:
        raise invalid_request("一次最多检索 16 个关键词")
    return terms


def _matches(terms: tuple[str, ...], *columns):
    return and_(true(), *(or_(*(column.icontains(term, autoescape=True) for column in columns)) for term in terms))


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


def _identifier_position(
    scope: str, cursor: str | None, kind: ResourceKind, project_ids: tuple[UUID, ...],
) -> tuple[UUID, str] | None:
    value = decode_position(scope, cursor)
    if value is None:
        return None
    if len(value) != 2 or not all(isinstance(field, str) for field in value):
        raise invalid_request("检索游标格式无效")
    project_id = parse_uuid(value[0], "cursor.project_id")
    if project_id not in project_ids:
        raise invalid_request("检索游标项目不在当前范围内")
    return project_id, ResourceRef(project_id, kind, value[1]).identifier


def _identifier_results(
    db: Session, statement, project_column, code_column, *, kind: ResourceKind,
    project_ids: tuple[UUID, ...], scope: str, cursor: str | None, limit: int,
):
    after = _identifier_position(scope, cursor, kind, project_ids)
    if after is not None:
        project, identifier = after
        code = parse_uuid(identifier, "cursor.id") if kind == ResourceKind.FILE else identifier
        statement = statement.where(tuple_(project_column, code_column) > tuple_(project, code))
    rows = list(db.execute(statement.order_by(project_column, code_column).limit(limit + 1)))
    if len(rows) <= limit:
        return rows, None
    last_project, last_id = rows[limit - 1][:2]
    return rows[:limit], encode_position(scope, [str(last_project), str(last_id)])


def _requirements(db: Session, project_ids: tuple[UUID, ...], terms: tuple[str, ...], filters: SearchFilters,
                  scope: str, cursor: str | None, limit: int) -> SearchPage:
    req = Requirement
    statement = select(req.project_id, req.code, req.title, req.description, req.status).where(
        req.project_id.in_(project_ids), req.deleted_at.is_(None), _matches(terms, req.code, req.title, req.description),
        *filters.time_predicates(req.updated_at),
    )
    if filters.requirement_status is not None:
        statement = statement.where(req.status == filters.requirement_status)
    rows, next_cursor = _identifier_results(db, statement, req.project_id, req.code, kind=ResourceKind.REQUIREMENT,
                                            project_ids=project_ids, scope=scope, cursor=cursor, limit=limit)
    overview = {}
    if rows:
        counts = db.execute(select(
            Task.project_id, Task.requirement_id, func.count(), func.count().filter(Task.status == "done"),
        ).where(Task.deleted_at.is_(None), tuple_(Task.project_id, Task.requirement_id).in_([
            (row.project_id, row.code) for row in rows
        ])).group_by(Task.project_id, Task.requirement_id))
        overview = {(project_id, code): (count, done) for project_id, code, count, done in counts}
    return SearchPage(items=[SearchItem(
        id=row.code, project_id=row.project_id, domain=SearchDomain.REQUIREMENT, title=row.title, status=row.status,
        href=ResourceRef(row.project_id, ResourceKind.REQUIREMENT, row.code).path,
        snippet=_snippet(terms, row.description, row.title, row.code),
        task_count=overview.get((row.project_id, row.code), (0, 0))[0],
        done_task_count=overview.get((row.project_id, row.code), (0, 0))[1],
    ) for row in rows], next_cursor=next_cursor)


def _timeline(db: Session, project_ids: tuple[UUID, ...], terms: tuple[str, ...], filters: SearchFilters,
              scope: str, cursor: str | None, limit: int) -> SearchPage:
    entry, revision, requirement = TimelineEntry, TimelineRevision, Requirement
    event_summary = entry.event_data["summary"].as_string()
    statement = select(
        entry.project_id, entry.id, entry.requirement_code, entry.occurred_at, requirement.title, revision.body,
        entry.event_type, event_summary.label("event_summary"),
    ).select_from(entry).outerjoin(
        revision, and_(revision.project_id == entry.project_id, revision.requirement_code == entry.requirement_code,
                       revision.entry_id == entry.id, revision.version == entry.latest_version),
    ).join(requirement, and_(requirement.project_id == entry.project_id, requirement.code == entry.requirement_code)).where(
        entry.project_id.in_(project_ids), requirement.deleted_at.is_(None),
        or_(entry.kind == "system", revision.kind != "withdraw"),
        *filters.time_predicates(entry.occurred_at),
    )
    if filters.timeline_kind is not None:
        statement = statement.where(entry.kind == filters.timeline_kind)
    if filters.timeline_actor_id is not None:
        statement = statement.where(entry.actor_id == filters.timeline_actor_id)
    if filters.timeline_source_task is not None:
        ResourceRef(project_ids[0], ResourceKind.TASK, filters.timeline_source_task)
        statement = statement.where(entry.source_task_code == filters.timeline_source_task)
    statement = statement.where(_matches(terms, revision.body, event_summary, entry.event_type))
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
        id=str(row.id), project_id=row.project_id, domain=SearchDomain.TIMELINE, title=row.title,
        requirement_id=row.requirement_code,
        href=f"{ResourceRef(row.project_id, ResourceKind.REQUIREMENT, row.requirement_code).path}#timeline-{row.id}",
        snippet=_snippet(terms, row.body, row.event_summary, row.event_type),
    ) for row in rows[:limit]], next_cursor=next_cursor)


def _wiki(db: Session, project_ids: tuple[UUID, ...], terms: tuple[str, ...], filters: SearchFilters,
          scope: str, cursor: str | None, limit: int) -> SearchPage:
    trees = [visible_wiki_tree(project_id) for project_id in project_ids]
    visible = or_(*(and_(
        Wiki.project_id == project_id, Wiki.code.in_(select(tree.c.code)),
    ) for project_id, tree in zip(project_ids, trees, strict=True)))
    statement = select(Wiki.project_id, Wiki.code, Wiki.title, Wiki.summary, Wiki.body).where(
        visible, _matches(terms, Wiki.title, Wiki.summary, Wiki.body), *filters.time_predicates(Wiki.updated_at),
    )
    if filters.wiki_category is not None:
        statement = statement.where(Wiki.category == filters.wiki_category)
    if filters.wiki_tag is not None:
        statement = statement.where(wiki_tag_predicate(db, filters.wiki_tag))
    rows, next_cursor = _identifier_results(db, statement, Wiki.project_id, Wiki.code, kind=ResourceKind.WIKI,
                                            project_ids=project_ids, scope=scope, cursor=cursor, limit=limit)
    return SearchPage(items=[SearchItem(
        id=row.code, project_id=row.project_id, domain=SearchDomain.WIKI, title=row.title,
        href=ResourceRef(row.project_id, ResourceKind.WIKI, row.code).path,
        snippet=_snippet(terms, row.body, row.summary, row.title),
    ) for row in rows], next_cursor=next_cursor)


def _files(db: Session, project_ids: tuple[UUID, ...], terms: tuple[str, ...], filters: SearchFilters,
           scope: str, cursor: str | None, limit: int) -> SearchPage:
    file = ProjectFile
    statement = select(file.project_id, file.id, file).where(
        file.project_id.in_(project_ids), file.deleted_at.is_(None), _matches(terms, file.name, file.media_type),
        *filters.time_predicates(file.created_at),
    )
    if filters.file_media_type is not None:
        statement = statement.where(file.media_type == filters.file_media_type.lower())
    if filters.file_uploader_id is not None:
        statement = statement.where(file.created_by == filters.file_uploader_id)
    if filters.file_used_at is not None:
        statement = statement.where(file_used_at_predicate(filters.file_used_at, project_ids))
    rows, next_cursor = _identifier_results(db, statement, file.project_id, file.id, kind=ResourceKind.FILE,
                                            project_ids=project_ids, scope=scope, cursor=cursor, limit=limit)
    return SearchPage(items=[SearchItem(
        domain=SearchDomain.FILE, title=row.name, snippet=_snippet(terms, row.name, row.media_type), **file_summary(row),
    ) for _, _, row in rows], next_cursor=next_cursor)


_SEARCH = {SearchDomain.REQUIREMENT: _requirements, SearchDomain.TIMELINE: _timeline, SearchDomain.WIKI: _wiki, SearchDomain.FILE: _files}


def search_project(
    db: Session, actor: User, project_id: UUID, *, query: str, domains: list[SearchDomain] | None = None,
    cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
    additional_project_ids: list[UUID] | None = None, filters: SearchFilters | None = None,
) -> SearchResult:
    if actor.deleted_at is not None:
        raise permission_denied("账号已停用")
    if additional_project_ids is not None and len(additional_project_ids) >= MAX_SEARCH_PROJECTS:
        raise invalid_request(f"每次最多选择 {MAX_SEARCH_PROJECTS} 个检索项目")
    project_ids = tuple(sorted({project_id, *(additional_project_ids or [])}))
    for selected in project_ids:
        get_accessible_project(db, actor.id, selected)

    terms = _query_terms(query)
    filters = filters or SearchFilters()
    filters.validate_range()
    filter_values = filters.model_dump(mode="json", exclude_none=True)
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise invalid_request(f"每个域须为 1 至 {MAX_PAGE_SIZE} 个结果")
    try:
        requested = list(dict.fromkeys(SearchDomain(domain) for domain in domains)) if domains is not None else list(SearchDomain)
    except ValueError:
        raise invalid_request("检索域须为 requirement、timeline、wiki 或 file") from None
    if not requested or (cursor is not None and len(requested) != 1):
        raise invalid_request("续页时通过 domains 明确选择一个检索域")
    if not terms and not filter_values:
        raise invalid_request("请输入关键词或选择筛选条件")
    if not terms and filters.from_at is None and filters.to_at is None:
        applicable = [domain for domain in requested if any(key.startswith(f"{domain}_") for key in filter_values)]
        if not applicable:
            raise invalid_request("请选择适用于检索域的筛选条件")
        requested = applicable
    return SearchResult(domains={
        domain: _SEARCH[domain](
            db, project_ids, terms, filters,
            scope_key("search.v2.scope", str(actor.id), str(project_id), [str(selected) for selected in project_ids],
                      domain, terms, filter_values, limit),
            cursor, limit,
        )
        for domain in requested
    })
