"""Permission-scoped discovery for explicitly deleted requirements and tasks."""

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import invalid_request, not_found
from ..models import Requirement, Task, User
from .pagination import decode_cursor, encode_cursor
from .permissions import require_project_role
from .projects import list_projects
from .short_codes import require_valid_code

WorkKind = Literal["requirement", "task"]


def _model(kind: WorkKind):
    if kind == "requirement":
        return Requirement
    if kind == "task":
        return Task
    raise invalid_request("仅支持 requirement 或 task")


def find_deleted(db: Session, actor: User, kind: WorkKind, code: str, project_id: UUID | None):
    model = _model(kind)
    require_valid_code(kind, code)
    query = select(model).where(Task.matches_code(code) if model is Task else model.code == code, model.deleted_at.is_not(None))
    if project_id is None:
        candidates = [project.id for project, role in list_projects(db, actor) if role in ("editor", "owner")]
        query = query.where(model.project_id.in_(candidates))
    else:
        require_project_role(db, actor.id, project_id, min_level="editor")
        query = query.where(model.project_id == project_id)
    rows = list(db.scalars(query.limit(2)))
    if not rows:
        raise not_found("已删除对象不存在")
    if len(rows) > 1:
        raise invalid_request("多个可管理项目存在同一短码，请指定 project_id")
    return rows[0]


def _summary(row: Requirement | Task) -> dict:
    return {
        "id": row.code, "project_id": str(row.project_id), "title": row.title, "status": row.status,
        "deleted_at": row.deleted_at.isoformat(), "deleted_by": str(row.deleted_by) if row.deleted_by else None,
        **({"requirement_id": row.requirement_id} if isinstance(row, Task) else {}),
    }


def list_deleted_work(
    db: Session, actor: User, project_id: UUID, kind: WorkKind, *,
    keyword: str = "", limit: int = 20, cursor: str | None = None,
) -> dict:
    require_project_role(db, actor.id, project_id, min_level="editor")
    model = _model(kind)
    keyword = keyword.strip()
    if len(keyword) > 256 or not 1 <= limit <= 100:
        raise invalid_request("回收站查询最多 256 字，每页 1 到 100 项")
    filters = {"project_id": str(project_id), "actor": str(actor.id), "kind": kind, "keyword": keyword}
    offset = decode_cursor(filters, cursor)
    query = select(model).where(model.project_id == project_id, model.deleted_at.is_not(None))
    if keyword:
        query = query.where(model.title.icontains(keyword, autoescape=True) | model.code.icontains(keyword, autoescape=True))
    rows = list(db.scalars(query.order_by(model.deleted_at.desc(), model.code).offset(offset).limit(limit + 1)))
    return {
        "items": [_summary(row) for row in rows[:limit]],
        "next_cursor": encode_cursor(filters, offset + limit, limit) if len(rows) > limit else None,
    }


def deleted_work_details(db: Session, actor: User, project_id: UUID, kind: WorkKind, code: str) -> dict:
    row = find_deleted(db, actor, kind, code, project_id)
    if isinstance(row, Requirement):
        count = db.scalar(select(func.count()).select_from(Task).where(
            Task.project_id == project_id, Task.requirement_id == row.code, Task.deleted_at.is_(None),
        ))
        return {**_summary(row), "description": row.description, "affected_tasks": count}
    return {**_summary(row), "description": row.description}


def restore_work(db: Session, actor: User, project_id: UUID, kind: WorkKind, code: str) -> dict:
    _model(kind)
    if kind == "requirement":
        from .requirements import restore_requirement

        restore_requirement(db, actor, code, project_id)
    else:
        from .tasks import restore_task

        restore_task(db, actor, code, project_id)
    return {"id": code, "project_id": str(project_id), "restored": True}
