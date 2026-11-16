"""全局搜索服务(规格书 §4.2 search.query / REQ-59 关键词读平面)。

- 需求/任务:标题/描述 LIKE 检索(既有行为保留);
- 文档(wiki):多关键词 AND 语义,标题/正文(frontmatter 去除)/别名参与,
  命中片段返回(替代前 300 字截断),相似度排序服务端计算
  (生产 PostgreSQL 由 pg_trgm GIN 索引加速候选过滤,排序不在 SQL 侧);
- 结果行与 INDEX 同构(doc_kind 标注 + summary/命中片段),读侧一种心智模型;
- Web 与 MCP 共用同一后端,结果按域分组合并后走 cursor 分页(services/pagination.py 规范)。
"""

import uuid

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from ..errors import invalid_request
from ..models import (
    Document,
    Project,
    ProjectMember,
    Requirement,
    Task,
    Team,
    User,
    WorkspaceMember,
)
from .documents import split_frontmatter
from .pagination import MAX_PAGE_SIZE, decode_cursor_page, page_result
from .permissions import get_team, is_admin, effective_user_id

SNIPPET_RADIUS = 50


def _accessible_project_ids(db: Session, user: User) -> list[uuid.UUID]:
    """用户有权限(含 admin 全量)的项目 id 列表。"""
    team = get_team(db)
    if is_admin(db, user.id):
        return list(
            db.scalars(
                select(Project.id).where(Project.team_id == team.id, Project.deleted_at.is_(None))
            ).all()
        )
    return list(
        db.scalars(
            select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.user_id == effective_user_id(db, user.id),
                Project.deleted_at.is_(None),
            )
        ).all()
    )


def _project_names(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not project_ids:
        return {}
    return {
        p.id: p.name
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }


def _needle(query: str) -> str:
    return query.strip().casefold()


def split_keywords(query: str) -> list[str]:
    """多关键词拆分:空白分隔;全小写化(SQLite LIKE 对 ASCII 不敏感,CJK 无大小写)。"""
    return [item.casefold() for item in query.strip().split() if item.strip()]


def _aliases_of(document: Document) -> list[str]:
    aliases = (document.doc_metadata or {}).get("aliases")
    if isinstance(aliases, str):
        return [aliases.casefold()]
    if isinstance(aliases, list):
        return [str(item).casefold() for item in aliases if str(item).strip()]
    return []


def _doc_kind_of(document: Document) -> str | None:
    kind = (document.doc_metadata or {}).get("doc_kind")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    return None


def _summary_of(document: Document, body: str) -> str:
    summary = (document.doc_metadata or {}).get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return " ".join(body.split())[:120]


def _snippet(body: str, position: int | None, keyword: str | None) -> str | None:
    """首个命中词上下文窗口片段(约 ±SNIPPET_RADIUS 字),无正文命中返回 None。"""
    if position is None or not keyword:
        return None
    flattened = " ".join(body.split())
    start = max(position - SNIPPET_RADIUS, 0)
    end = min(position + len(keyword) + SNIPPET_RADIUS, len(flattened))
    snippet = flattened[start:end]
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flattened) else ""
    return f"{prefix}{snippet}{suffix}"


def _match_document(document: Document, keywords: list[str]) -> dict | None:
    """多关键词 AND 匹配+打分;不满足任一关键词返回 None。

    打分(简单可解释):标题命中 +10/词,别名命中 +4/词,正文命中 +2/词;
    短词(<2 字符)走同一包含匹配——LIKE 兜底语义,与设计「短词兜底」一致。
    """
    title_cf = document.title.casefold()
    _frontmatter, body = split_frontmatter(document.content)
    content_cf = body.casefold()
    aliases = _aliases_of(document)
    summary = (document.doc_metadata or {}).get("summary")
    summary_cf = summary.casefold() if isinstance(summary, str) else ""
    score = 0
    first_pos: int | None = None
    first_keyword: str | None = None
    for keyword in keywords:
        in_title = keyword in title_cf
        in_aliases = any(keyword == alias or keyword in alias for alias in aliases)
        in_content = keyword in content_cf
        in_summary = bool(summary_cf) and keyword in summary_cf
        if not (in_title or in_aliases or in_content or in_summary):
            return None
        if in_title:
            score += 10
        if in_aliases:
            score += 4
        if in_summary:
            score += 3
        if in_content:
            score += 2
            pos = content_cf.find(keyword)
            if pos >= 0 and (first_pos is None or pos < first_pos):
                first_pos = pos
                first_keyword = keyword
    return {
        "score": score,
        "snippet": _snippet(body, first_pos, first_keyword),
        "summary": _summary_of(document, body),
        "doc_kind": _doc_kind_of(document),
    }


def _document_candidates(
    db: Session, project_ids: list[uuid.UUID], keywords: list[str]
) -> list[Document]:
    """候选过滤:任一关键词命中标题/正文/metadata(JSON 文本)即入候选,
    精确 AND 语义与别名参与由 Python 侧完成(GIN 仅加速候选,排序服务端计算)。"""
    if not project_ids or not keywords:
        return []
    conditions = []
    for keyword in keywords:
        like = f"%{keyword}%"
        conditions.append(
            or_(
                Document.title.ilike(like),
                Document.content.ilike(like),
                cast(Document.doc_metadata, String).ilike(like),
            )
        )
    return db.scalars(
        select(Document).where(
            Document.project_id.in_(project_ids),
            Document.deleted_at.is_(None),
            or_(*conditions),
        )
    ).all()


def search_documents(db: Session, project_ids: list[uuid.UUID], query: str) -> list[dict]:
    """跨项目文档检索(search.query 的 document 域):多关键词 AND+片段+同构行。"""
    keywords = split_keywords(query)
    candidates = _document_candidates(db, project_ids, keywords)
    rows: list[dict] = []
    for document in candidates:
        match = _match_document(document, keywords)
        if match is None:
            continue
        rows.append(
            {
                "domain": "document",
                "id": document.code,
                "project_id": str(document.project_id),
                "doc_type": document.doc_type,
                "doc_kind": match["doc_kind"],
                "title": document.title,
                "summary": match["summary"],
                "snippet": match["snippet"],
                "updated_at": document.updated_at.isoformat(),
                "score": match["score"],
            }
        )
    rows.sort(key=lambda row: (-row["score"], row["title"].casefold()))
    return rows


def search_documents_paged(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    query: str,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict:
    """项目内 wiki 检索(docs.search MCP):权限校验+cursor 分页,行与 INDEX 同构。"""
    from .permissions import get_accessible_project

    get_accessible_project(db, user.id, project_id, min_level="viewer")
    query = query.strip()
    if not query:
        raise invalid_request("检索词不能为空")
    if limit is not None and (limit < 1 or limit > MAX_PAGE_SIZE):
        raise invalid_request("limit 必须在 1..100 之间")
    filters = {"project_id": str(project_id), "q": query}
    offset, page_size = decode_cursor_page(filters, cursor, limit)
    rows = search_documents(db, [project_id], query)
    page = rows[offset : offset + page_size]
    return page_result(page, offset, page_size, filters)


def search_requirements(db: Session, project_ids: list[uuid.UUID], query: str) -> list[dict]:
    needle = _needle(query)
    if not project_ids or not needle:
        return []
    rows = db.scalars(
        select(Requirement).where(
            Requirement.project_id.in_(project_ids),
            Requirement.deleted_at.is_(None),
            or_(
                Requirement.title.ilike(f"%{needle}%"),
                Requirement.description.ilike(f"%{needle}%"),
            ),
        )
        .order_by(Requirement.updated_at.desc(), Requirement.code)
    ).all()
    return [
        {
            "domain": "requirement",
            "id": r.code,
            "project_id": str(r.project_id),
            "title": r.title,
            "summary": r.description or "",
            "status": r.status,
        }
        for r in rows
    ]


def search_tasks(db: Session, project_ids: list[uuid.UUID], query: str) -> list[dict]:
    needle = _needle(query)
    if not project_ids or not needle:
        return []
    rows = db.scalars(
        select(Task).where(
            Task.project_id.in_(project_ids),
            Task.deleted_at.is_(None),
            or_(
                Task.title.ilike(f"%{needle}%"),
                Task.description.ilike(f"%{needle}%"),
            ),
        )
        .order_by(Task.updated_at.desc(), Task.code)
    ).all()
    return [
        {
            "domain": "task",
            "id": t.code,
            "project_id": str(t.project_id),
            "title": t.title,
            "summary": t.description or "",
            "status": t.status,
        }
        for t in rows
    ]


def _cursor_filters(query: str, domains: list[str] | None) -> dict:
    """游标条件哈希绑定查询词与域过滤集合。"""
    return {"q": query, "domains": sorted(set(domains)) if domains else None}


def search(
    db: Session,
    user: User,
    query: str,
    domains: list[str] | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> dict:
    """跨域搜索,返回 {items, next_cursor}(cursor 分页,见 services/pagination.py)。

    domains 为 None 表示全部域;默认页大小 DEFAULT_PAGE_SIZE,limit 可在 1..MAX_PAGE_SIZE 内调整。
    """
    project_ids = _accessible_project_ids(db, user)
    query = query.strip()
    if not project_ids or not query:
        return {"items": []}
    if limit is not None and (limit < 1 or limit > MAX_PAGE_SIZE):
        raise invalid_request("limit 必须在 1..100 之间")
    filters = _cursor_filters(query, domains)
    offset, page_size = decode_cursor_page(filters, cursor, limit)
    requested = set(domains) if domains else None

    items: list[dict] = []
    if requested is None or "requirement" in requested:
        items.extend(search_requirements(db, project_ids, query))
    if requested is None or "task" in requested:
        items.extend(search_tasks(db, project_ids, query))
    if requested is None or "document" in requested:
        items.extend(search_documents(db, project_ids, query))

    if items:
        names = _project_names(db, project_ids)
        for item in items:
            item["project_name"] = names.get(uuid.UUID(item["project_id"]), "")
    page = items[offset : offset + page_size]
    return page_result(page, offset, page_size, filters)
