"""Backlinks from the current visible Wiki and work-item Markdown bodies."""
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, literal, select, tuple_, union_all
from sqlalchemy.orm import Session

from ..errors import invalid_request
from ..models import Requirement, Task, User
from . import work_content
from .page_cursor import decode_position, encode_position, scope_key
from .resource_refs import ResourceKind, ResourceRef
from .wiki import read_wiki, visible_wiki_codes
from .wiki_models import Wiki, WikiReference
from .work_content_models import WorkReference

BodyKind = Literal["requirements", "tasks", "wiki"]


def list_backlinks(db: Session, actor: User, project_id: UUID, target_kind: BodyKind, target_id: str,
                   cursor: str | None = None, limit: int = 50) -> dict:
    if not 1 <= limit <= 100:
        raise invalid_request("limit 必须在 1..100 之间")
    if target_kind == "wiki":
        target = read_wiki(db, actor.id, project_id, target_id)
    else:
        target = work_content._item(db, actor, project_id, target_kind, target_id)
    ids = [target.code]
    if isinstance(target, Task) and target.legacy_code:
        ids.append(target.legacy_code)
    sources = [(Wiki, WikiReference, "wiki", WikiReference.wiki_code, WikiReference.version_no,
                Wiki.version_no, Wiki.code.in_(visible_wiki_codes(project_id)))]
    for model, kind in ((Requirement, "requirements"), (Task, "tasks")):
        visible = model.deleted_at.is_(None)
        if model is Task:
            visible = and_(visible, Task.has_active_requirement())
        sources.append((model, WorkReference, kind, WorkReference.code, WorkReference.version, model.version, visible))
    selects = [
        select(literal(kind).label("kind"), model.code.label("code"), model.title.label("title")).join(
            index, and_(model.project_id == index.project_id, model.code == indexed_code, version == indexed_version)
        ).where(model.project_id == project_id, index.target_kind == target_kind, index.target_id.in_(ids), visible).distinct()
        for model, index, kind, indexed_code, indexed_version, version, visible in sources
    ]
    rows = union_all(*selects).subquery()
    query = select(rows).order_by(rows.c.kind, rows.c.code)
    scope = scope_key("markdown.backlinks", str(project_id), target_kind, target.code)
    position = decode_position(scope, cursor)
    if position is not None:
        if len(position) != 2 or not all(isinstance(value, str) for value in position):
            raise invalid_request("游标无效")
        query = query.where(tuple_(rows.c.kind, rows.c.code) > tuple(position))
    found = db.execute(query.limit(limit + 1)).all()
    items = [{"kind": kind, "id": code, "title": title, "href": ResourceRef(project_id, ResourceKind(kind), code).path}
             for kind, code, title in found[:limit]]
    next_cursor = encode_position(scope, [items[-1]["kind"], items[-1]["id"]]) if len(found) > limit else None
    return {"items": items, "next_cursor": next_cursor}
