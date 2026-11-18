"""Explicit replies and Markdown person mentions. No transport commits here."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..errors import invalid_request, not_found, permission_denied
from ..models import Project, ProjectMember, Requirement, Task, User
from ..services.permissions import get_project_role, get_workspace_member, is_admin
from .markdown_refs import extract_markdown_refs
from .notification_models import Notification
from .page_cursor import as_utc, decode_time_position, encode_position, scope_key
from .resource_refs import ResourceKind, ResourceRef
from .timeline_models import TimelineEntry
from .wiki_models import visible_wiki_tree


_BODY_KINDS = {
    ResourceKind.WIKI: "wiki",
    ResourceKind.REQUIREMENT: "requirement",
    ResourceKind.TASK: "task",
}
_SOURCE_RESOURCES = {name: kind for kind, name in _BODY_KINDS.items()} | {"timeline": ResourceKind.REQUIREMENT}


@dataclass
class Recipient:
    mentions: set[UUID] = field(default_factory=set)
    reply_user_id: UUID | None = None
    owner_only: bool = False


def _owner(db: Session, user: User) -> UUID | None:
    if user.deleted_at is not None:
        return None
    owner = db.get(User, user.owner_id) if user.is_agent and user.owner_id else user
    if owner is None or owner.is_agent or owner.deleted_at is not None:
        return None
    return owner.id if get_workspace_member(db, owner.id) is not None else None


def _mentions(body: str | None, project_id: UUID) -> set[UUID]:
    if not body:
        return set()
    return {
        UUID(ref.identifier) for ref in extract_markdown_refs(body, project_id, include_images=False)
        if ref.kind == ResourceKind.PERSON
    }


def emit_markdown_notifications(
    db: Session, actor_id: UUID, *, source: ResourceRef, source_version: int, body: str,
    previous_body: str | None = None, timeline_entry_id: UUID | None = None,
    reply_author_id: UUID | None = None,
) -> None:
    """Trusted save hook, called after the source is flushed and before commit.

    Creates at most one notification per owner and source version, even when
    both identities are mentioned or a reply and a mention reach the same owner.
    """
    if source.kind == ResourceKind.REQUIREMENT and timeline_entry_id is not None:
        source_kind, source_key = "timeline", str(timeline_entry_id)
    elif source.kind in _BODY_KINDS and timeline_entry_id is None and reply_author_id is None:
        source_kind, source_key = _BODY_KINDS[source.kind], source.identifier
    else:
        raise ValueError("Unsupported Markdown notification source")
    mentioned = _mentions(body, source.project_id) - _mentions(previous_body, source.project_id)
    recipients = mentioned | ({reply_author_id} if reply_author_id else set())
    recipients.discard(actor_id)
    if not recipients:
        return
    actor = db.get(User, actor_id)
    if actor is None or _owner(db, actor) is None:
        raise permission_denied("通知发起人已停用或不属于当前工作区")
    groups: dict[UUID, Recipient] = {}
    for user in db.scalars(select(User).where(User.id.in_(recipients), User.deleted_at.is_(None))):
        owner_id = _owner(db, user)
        if owner_id is None or get_project_role(db, owner_id, source.project_id) is None:
            continue
        group = groups.setdefault(owner_id, Recipient())
        if user.id in mentioned:
            group.mentions.add(user.id)
        if user.id == reply_author_id:
            group.reply_user_id = user.id
        if actor.is_agent and actor.owner_id == user.id:
            group.owner_only = True
    if not groups:
        return
    now = datetime.now(UTC)
    rows = [{
        "project_id": source.project_id, "owner_id": owner_id, "actor_id": actor_id,
        "visibility": "owner_only" if group.owner_only else "shared",
        "source_kind": source_kind, "source_key": source_key, "source_code": source.identifier,
        "source_version": source_version, "entry_id": timeline_entry_id,
        "mentioned_user_ids": sorted(str(identity) for identity in group.mentions),
        "reply_user_id": group.reply_user_id, "created_at": now,
    } for owner_id, group in groups.items()]
    statement = {"postgresql": pg_insert, "sqlite": sqlite_insert}[db.get_bind().dialect.name]
    db.execute(statement(Notification).values(rows).on_conflict_do_nothing(
        index_elements=["project_id", "source_kind", "source_key", "source_version", "owner_id"],
    ))


def _visibility(db: Session, actor: User):
    owner_id = _owner(db, actor)
    if owner_id is None:
        raise permission_denied("账号已停用或不属于当前工作区")
    timeline_visible = select(TimelineEntry.id).join(Requirement, and_(
        Requirement.project_id == TimelineEntry.project_id,
        Requirement.code == TimelineEntry.requirement_code,
    )).where(
        TimelineEntry.project_id == Notification.project_id,
        TimelineEntry.requirement_code == Notification.source_code,
        TimelineEntry.id == Notification.entry_id, Requirement.deleted_at.is_(None),
    ).exists()
    tree = visible_wiki_tree()
    wiki_visible = select(tree.c.code).where(
        tree.c.project_id == Notification.project_id, tree.c.code == Notification.source_code,
    ).exists()
    requirement_visible = select(Requirement.code).where(
        Requirement.project_id == Notification.project_id, Requirement.code == Notification.source_code,
        Requirement.deleted_at.is_(None),
    ).exists()
    task_visible = select(Task.code).where(
        Task.project_id == Notification.project_id, Task.code == Notification.source_code,
        Task.deleted_at.is_(None), Task.has_active_requirement(),
    ).exists()
    active_project = select(Project.id).where(Project.deleted_at.is_(None))
    if not is_admin(db, owner_id):
        active_project = active_project.join(ProjectMember, ProjectMember.project_id == Project.id).where(
            ProjectMember.user_id == owner_id,
        )
    query = select(Notification).where(
        Notification.owner_id == owner_id, Notification.project_id.in_(active_project),
        or_(and_(Notification.source_kind == "timeline", timeline_visible),
            and_(Notification.source_kind == "wiki", wiki_visible),
            and_(Notification.source_kind == "requirement", requirement_visible),
            and_(Notification.source_kind == "task", task_visible)),
    )
    if actor.is_agent:
        query = query.where(Notification.visibility == "shared")
    return owner_id, query


def _data(item: Notification) -> dict[str, Any]:
    kind = _SOURCE_RESOURCES[item.source_kind]
    path = ResourceRef(item.project_id, kind, item.source_code).path
    if item.entry_id is not None:
        path += f"#timeline-{item.entry_id}"
    elif item.source_kind == "requirement":
        path += "?tab=body"
    return {
        "id": str(item.id), "project_id": str(item.project_id), "actor_id": str(item.actor_id),
        "visibility": item.visibility, "source_kind": item.source_kind, "source_path": path,
        "source_code": item.source_code, "source_version": item.source_version,
        "entry_id": str(item.entry_id) if item.entry_id is not None else None,
        "mentioned_user_ids": item.mentioned_user_ids,
        "reply_user_id": str(item.reply_user_id) if item.reply_user_id else None,
        "created_at": as_utc(item.created_at).isoformat(),
        "read_at": as_utc(item.read_at).isoformat() if item.read_at else None,
        "read_by_id": str(item.read_by_id) if item.read_by_id else None,
    }


def list_notifications(
    db: Session, actor: User, *, cursor: str | None = None, limit: int = 20,
    unread_only: bool = False,
) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise invalid_request("每页通知数须为 1 至 100")
    owner_id, query = _visibility(db, actor)
    scope = scope_key("notifications", str(actor.id), str(owner_id), unread_only)
    position = decode_time_position(scope, cursor)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if position is not None:
        cutoff, item_id = position
        query = query.where(or_(
            Notification.created_at < cutoff,
            and_(Notification.created_at == cutoff, Notification.id < item_id),
        ))
    rows = db.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)).all()
    last = rows[limit - 1] if len(rows) > limit else None
    return {"items": [_data(item) for item in rows[:limit]], "next_cursor": (
        encode_position(scope, [as_utc(last.created_at).isoformat(), str(last.id)]) if last else None
    )}


def unread_count(db: Session, actor: User) -> int:
    _, query = _visibility(db, actor)
    return db.scalar(query.where(Notification.read_at.is_(None)).with_only_columns(func.count())) or 0


def get_notification(db: Session, actor: User, item_id: UUID) -> dict[str, Any]:
    _, query = _visibility(db, actor)
    item = db.scalar(query.where(Notification.id == item_id))
    if item is None:
        raise not_found("通知不存在或来源已不可见")
    return _data(item)


def mark_read(db: Session, actor: User, item_id: UUID) -> dict[str, Any]:
    """Write the first reader once even if both identities acknowledge concurrently."""
    _, query = _visibility(db, actor)
    query = query.where(Notification.id == item_id)
    db.execute(
        update(Notification).where(
            Notification.id.in_(query.with_only_columns(Notification.id)),
            Notification.read_at.is_(None),
        ).values(read_at=datetime.now(UTC), read_by_id=actor.id).execution_options(synchronize_session=False)
    )
    item = db.scalar(query.execution_options(populate_existing=True))
    if item is None:
        raise not_found("通知不存在或来源已不可见")
    return _data(item)
