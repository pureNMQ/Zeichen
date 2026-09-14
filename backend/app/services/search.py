"""全局搜索服务(规格书 §4.2 search.query / frontend-requirements §2.5)。

- 关键词部分:业务实体(需求/任务/文档)SQL LIKE 检索,跨用户有权限的全部项目
- 语义部分:记忆域经 cognee recall 检索,同样限定在有权限的项目内
- Web 与 MCP 共用同一后端,结果按域分组合并后走 cursor 分页(services/pagination.py 规范)
"""

import uuid

from sqlalchemy import or_, select
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
from .pagination import MAX_PAGE_SIZE, decode_cursor_page, page_result
from .permissions import get_team, is_admin, effective_user_id


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


def search_documents(db: Session, project_ids: list[uuid.UUID], query: str) -> list[dict]:
    needle = _needle(query)
    if not project_ids or not needle:
        return []
    rows = db.scalars(
        select(Document).where(
            Document.project_id.in_(project_ids),
            Document.deleted_at.is_(None),
            or_(
                Document.title.ilike(f"%{needle}%"),
                Document.content.ilike(f"%{needle}%"),
            ),
        )
        .order_by(Document.updated_at.desc(), Document.code)
    ).all()
    return [
        {
            "domain": "document",
            "id": d.code,
            "project_id": str(d.project_id),
            "doc_type": d.doc_type,
            "title": d.title,
            "summary": (d.content or "")[:300],
        }
        for d in rows
    ]


def search_memory(
    db: Session, project_ids: list[uuid.UUID], query: str, client=None
) -> list[dict]:
    """语义检索:对每个有权限项目的 Dataset 调用 cognee recall,汇总相关片段。

    每个项目最多取 recall 前 3 条(相关性截取);跨项目按 project_id 排序保证分页顺序稳定。
    """
    if not project_ids or not query.strip():
        return []
    from .cognee import CogneeClient
    from .memory import _dataset

    client = client or CogneeClient()
    results: list[dict] = []
    for project_id in sorted(project_ids):
        try:
            dataset = _dataset(db, project_id, client, create=False)
        except Exception:
            continue
        try:
            payload = client.recall(dataset_id=dataset.cognee_dataset_id, query=query)
        except Exception:
            continue
        items = _extract_recall_text(payload)
        for text in items[:3]:
            results.append(
                {
                    "domain": "memory",
                    "project_id": str(project_id),
                    "title": "记忆",
                    "summary": text,
                }
            )
    return results


def _extract_recall_text(payload) -> list[str]:
    if not isinstance(payload, dict):
        return []
    parts: list[str] = []
    for answer in payload.get("answers") or []:
        if isinstance(answer, dict):
            text = answer.get("answer") or answer.get("text")
            if text:
                parts.append(str(text))
    if not parts:
        for chunk in payload.get("chunks") or []:
            if isinstance(chunk, dict) and chunk.get("text"):
                parts.append(str(chunk["text"]))
    return parts


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
    client=None,
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
    if requested is None or "memory" in requested:
        items.extend(search_memory(db, project_ids, query, client))

    if items:
        names = _project_names(db, project_ids)
        for item in items:
            item["project_name"] = names.get(uuid.UUID(item["project_id"]), "")
    page = items[offset : offset + page_size]
    return page_result(page, offset, page_size, filters)
