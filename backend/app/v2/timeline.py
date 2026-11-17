"""Requirement timeline domain. Service methods join the caller's transaction."""

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Requirement, Task, User
from ..services.permissions import require_project_role
from .commands import execute_once
from .notifications import emit_markdown_notifications
from .page_cursor import as_utc as _utc
from .page_cursor import decode_position as _decode
from .page_cursor import decode_time_position
from .page_cursor import encode_position as _encode
from .page_cursor import scope_key
from .resource_refs import ResourceKind, ResourceRef
from .timeline_models import TimelineEntry, TimelineRevision


MAX_BODY = 32_768
MAX_REASON = 512
MAX_PREVIEW = 240
MAX_VERSION = 2_147_483_647
_E = TimelineEntry
_R = TimelineRevision


def _authorize(db: Session, actor: User, scope: ResourceRef, level: str) -> str:
    if scope.kind != ResourceKind.REQUIREMENT:
        raise invalid_request("时间轴必须属于需求")
    if actor.deleted_at is not None:
        raise permission_denied("账号已停用")
    role = require_project_role(db, actor.id, scope.project_id, min_level=level)
    requirement = db.scalar(
        select(Requirement.code).where(
            Requirement.project_id == scope.project_id, Requirement.code == scope.identifier,
            Requirement.deleted_at.is_(None),
        )
    )
    if requirement is None:
        raise not_found("需求不存在")
    return role


def _entries(scope: ResourceRef):
    return _E.project_id == scope.project_id, _E.requirement_code == scope.identifier


def _revisions(scope: ResourceRef):
    return _R.project_id == scope.project_id, _R.requirement_code == scope.identifier


def _entry(db: Session, scope: ResourceRef, entry_id: UUID) -> TimelineEntry:
    result = db.scalar(select(_E).where(*_entries(scope), _E.id == entry_id))
    if result is None:
        raise not_found("时间轴记录不存在")
    return result


def _source_task(db: Session, scope: ResourceRef, source_task: str | None) -> str | None:
    if source_task is None:
        return None
    source = ResourceRef(scope.project_id, ResourceKind.TASK, source_task)
    task_code = db.scalar(
        select(Task.code).where(
            Task.project_id == source.project_id, Task.code == source.identifier,
            Task.requirement_id == scope.identifier, Task.deleted_at.is_(None),
        )
    )
    if task_code is None:
        raise not_found("来源任务不属于当前需求或不可见")
    return task_code


def _validate_body(body: str) -> str:
    if not isinstance(body, str) or not body.strip() or len(body) > MAX_BODY or "\x00" in body:
        raise invalid_request(f"Markdown 正文须包含 1 至 {MAX_BODY} 个有效字符")
    return body.replace("\r\n", "\n").replace("\r", "\n")


def _new_revision(entry: TimelineEntry, actor: User, version: int,
                  kind: str, body: str | None, reason: str | None = None) -> TimelineRevision:
    return _R(
        entry_id=entry.id, project_id=entry.project_id, requirement_code=entry.requirement_code,
        version=version, kind=kind, body=body, reason=reason, actor_id=actor.id,
        created_at=datetime.now(UTC),
    )


def _receipt(entry_id: UUID, version: int) -> dict[str, Any]:
    return {"entry_id": str(entry_id), "version": version, "warnings": []}


def append_entry(
    db: Session, actor: User, scope: ResourceRef, *, request_id: UUID,
    body: str, source_task: str | None = None, reply_to: UUID | None = None,
) -> dict[str, Any]:
    """Append manual Markdown and its first revision exactly once."""
    _authorize(db, actor, scope, "editor")
    body = _validate_body(body)
    payload = {"requirement": scope.identifier, "body": body, "source_task": source_task,
               "reply_to": str(reply_to) if reply_to is not None else None}

    def apply() -> dict[str, Any]:
        replied_to = _entry(db, scope, reply_to) if reply_to is not None else None
        entry = _E(
            project_id=scope.project_id, requirement_code=scope.identifier,
            occurred_at=datetime.now(UTC), actor_id=actor.id, kind="manual", latest_version=1,
            source_task_code=_source_task(db, scope, source_task), reply_to_id=reply_to,
        )
        db.add(entry)
        db.flush()
        db.add(_new_revision(entry, actor, 1, "create", body))
        db.flush()
        emit_markdown_notifications(
            db, actor.id, source=scope, source_version=1, body=body, timeline_entry_id=entry.id,
            reply_author_id=replied_to.actor_id if replied_to else None,
        )
        return _receipt(entry.id, 1)

    return execute_once(db, project_id=scope.project_id, actor_id=actor.id,
                        operation="timeline.append", request_id=request_id, payload=payload, apply=apply)


def record_system_event(
    db: Session, actor_id: UUID | None, scope: ResourceRef, *, event_type: str,
    event_data: dict[str, Any], source_task: str | None = None,
) -> TimelineEntry:
    """Trusted mutation hook. The originating command already checks authorization."""
    if scope.kind != ResourceKind.REQUIREMENT:
        raise invalid_request("时间轴必须属于需求")
    entry = _E(
        project_id=scope.project_id, requirement_code=scope.identifier,
        occurred_at=datetime.now(UTC), actor_id=actor_id, kind="system",
        event_type=event_type, event_data=event_data, source_task_code=source_task,
    )
    db.add(entry)
    db.flush()
    return entry


def _mutate_revision(
    db: Session, actor: User, scope: ResourceRef, entry_id: UUID, *, request_id: UUID,
    expected_version: int, kind: str, body: str | None, reason: str | None,
) -> dict[str, Any]:
    role = _authorize(db, actor, scope, "editor")
    entry = _entry(db, scope, entry_id)
    if entry.kind != "manual":
        raise conflict("系统时间轴记录不能修订或撤回")
    is_author = entry.actor_id == actor.id
    if not is_author and role != "owner":
        raise permission_denied("只能管理本人的记录")
    if reason is not None:
        reason = reason.strip() or None
    if reason is not None and (len(reason) > MAX_REASON or "\x00" in reason):
        raise invalid_request(f"操作原因不能超过 {MAX_REASON} 个字符")
    if not is_author and not reason:
        raise invalid_request("管理他人的记录时必须填写原因")
    if type(expected_version) is not int or not 1 <= expected_version < MAX_VERSION:
        raise invalid_request("expected_version 超出有效范围")
    payload = {"requirement": scope.identifier, "entry_id": str(entry_id),
               "expected_version": expected_version, "body": body, "reason": reason}

    def apply() -> dict[str, Any]:
        latest = db.execute(
            select(_R.kind, _R.body).where(*_revisions(scope), _R.entry_id == entry_id,
                                          _R.version == expected_version)
        ).one_or_none()
        if latest is not None and latest.kind == "withdraw":
            raise conflict("此记录已撤回，请追加新记录")
        version = expected_version + 1
        changed = db.execute(
            update(_E).where(*_entries(scope), _E.id == entry_id, _E.latest_version == expected_version)
            .values(latest_version=version).returning(_E.id)
        ).scalar_one_or_none()
        if changed is None:
            raise conflict("时间轴版本已更新，请重新读取后再操作")
        db.add(_new_revision(entry, actor, version, kind, body, reason))
        db.flush()
        if body is not None:
            emit_markdown_notifications(
                db, actor.id, source=scope, source_version=version, body=body,
                previous_body=latest.body if latest is not None else None, timeline_entry_id=entry.id,
            )
        return _receipt(entry_id, version)

    return execute_once(db, project_id=scope.project_id, actor_id=actor.id,
                        operation=f"timeline.{kind}", request_id=request_id, payload=payload, apply=apply)


def revise_entry(
    db: Session, actor: User, scope: ResourceRef, entry_id: UUID, *, request_id: UUID,
    expected_version: int, body: str, reason: str | None = None,
) -> dict[str, Any]:
    return _mutate_revision(db, actor, scope, entry_id, request_id=request_id,
                            expected_version=expected_version, kind="revise",
                            body=_validate_body(body), reason=reason)


def withdraw_entry(
    db: Session, actor: User, scope: ResourceRef, entry_id: UUID, *, request_id: UUID,
    expected_version: int, reason: str | None = None,
) -> dict[str, Any]:
    return _mutate_revision(db, actor, scope, entry_id, request_id=request_id,
                            expected_version=expected_version, kind="withdraw", body=None, reason=reason)


def _datetime_filter(value: datetime | None) -> datetime | None:
    if value is not None and value.utcoffset() is None:
        raise invalid_request("筛选时间必须包含时区")
    return _utc(value) if value is not None else None


def _list_scope(kind: str, actor: User, scope: ResourceRef, filters: list[Any]) -> str:
    return scope_key(kind, str(actor.id), scope.path, filters)


def _limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise invalid_request("每页记录数须为 1 至 100")


def _current(scope: ResourceRef):
    join = and_(*_revisions(scope), _R.entry_id == _E.id, _R.version == _E.latest_version)
    return select(_E, _R).outerjoin(_R, join).where(*_entries(scope))


def _preview(revision: TimelineRevision | None, keyword: str | None = None) -> str | None:
    if revision is None or revision.body is None:
        return None
    body = revision.body
    if keyword is not None and (match := re.search(re.escape(keyword), body, re.IGNORECASE)):
        start = max(0, match.start() - 40)
        end = max(start + MAX_PREVIEW, match.end())
        return ("…" if start else "") + body[start:end] + ("…" if end < len(body) else "")
    return body[:MAX_PREVIEW]


def _reply_lookup(db: Session, scope: ResourceRef, items) -> dict[UUID, dict[str, Any]]:
    ids = {entry.reply_to_id for entry, _ in items if entry.reply_to_id is not None}
    if not ids:
        return {}
    return {
        entry.id: {"entry_id": str(entry.id), "actor_id": str(entry.actor_id) if entry.actor_id else None,
                   "kind": entry.kind, "withdrawn": bool(revision and revision.kind == "withdraw"),
                   "body_preview": _preview(revision), "event_type": entry.event_type}
        for entry, revision in db.execute(_current(scope).where(_E.id.in_(ids)))
    }


def _recorded_actors(db: Session, rows) -> dict[UUID, User]:
    actor_ids = {entry.actor_id for entry, _ in rows if entry.actor_id is not None}
    if not actor_ids:
        return {}
    return {user.id: user for user in db.scalars(select(User).where(User.id.in_(actor_ids)))}


def _entry_data(entry: TimelineEntry, revision: TimelineRevision | None,
                replies: dict[UUID, dict[str, Any]], actors: dict[UUID, User], *,
                detail: bool = False, keyword: str | None = None) -> dict[str, Any]:
    author = actors.get(entry.actor_id)
    result = {
        "id": str(entry.id), "project_id": str(entry.project_id), "requirement_id": entry.requirement_code,
        "kind": entry.kind, "actor_id": str(entry.actor_id) if entry.actor_id else None,
        "actor_name": (author.nickname or author.username) if author else None,
        "actor_is_agent": bool(author and author.is_agent),
        "occurred_at": _utc(entry.occurred_at).isoformat(), "source_task": entry.source_task_code,
        "reply_to": replies.get(entry.reply_to_id), "version": entry.latest_version,
        "revised": bool(revision and revision.version > 1),
        "withdrawn": bool(revision and revision.kind == "withdraw"),
        "event_type": entry.event_type, "event_data": entry.event_data,
    }
    if detail:
        result["body"] = revision.body if revision else None
    else:
        result["body_preview"] = _preview(revision, keyword)
    return result


def list_entries(
    db: Session, actor: User, scope: ResourceRef, *, cursor: str | None = None,
    limit: int = 20, kind: str | None = None, actor_id: UUID | None = None,
    source_task: str | None = None, keyword: str | None = None,
    from_at: datetime | None = None, to_at: datetime | None = None,
) -> dict[str, Any]:
    """Newest-first stable history; next_cursor moves toward older records."""
    _authorize(db, actor, scope, "viewer")
    _limit(limit)
    if kind not in (None, "manual", "system"):
        raise invalid_request("记录类型须为 manual 或 system")
    if source_task is not None:
        ResourceRef(scope.project_id, ResourceKind.TASK, source_task)
    keyword = (keyword.strip() or None) if keyword is not None else None
    if keyword is not None and (len(keyword) > 256 or "\x00" in keyword):
        raise invalid_request("时间轴搜索词不能超过 256 个字符")
    start, end = _datetime_filter(from_at), _datetime_filter(to_at)
    if start and end and start > end:
        raise invalid_request("开始时间不能晚于结束时间")
    cursor_scope = _list_scope("entries", actor, scope, [
        kind, str(actor_id) if actor_id is not None else None, source_task, keyword,
        start.isoformat() if start else None, end.isoformat() if end else None,
    ])
    statement = _current(scope)
    if kind is not None:
        statement = statement.where(_E.kind == kind)
    if actor_id is not None:
        statement = statement.where(_E.actor_id == actor_id)
    if source_task is not None:
        statement = statement.where(_E.source_task_code == source_task)
    if keyword is not None:
        statement = statement.where(_R.body.icontains(keyword, autoescape=True))
    if start is not None:
        statement = statement.where(_E.occurred_at >= start)
    if end is not None:
        statement = statement.where(_E.occurred_at <= end)
    position = decode_time_position(cursor_scope, cursor)
    if position is not None:
        cutoff, entry_id = position
        statement = statement.where(or_(
            _E.occurred_at < cutoff,
            and_(_E.occurred_at == cutoff, _E.id < entry_id),
        ))
    rows = db.execute(statement.order_by(_E.occurred_at.desc(), _E.id.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    replies = _reply_lookup(db, scope, items)
    next_cursor = None
    if len(rows) > limit:
        last = items[-1][0]
        next_cursor = _encode(cursor_scope, [_utc(last.occurred_at).isoformat(), str(last.id)])
    actors = _recorded_actors(db, items)
    return {"items": [_entry_data(entry, revision, replies, actors, keyword=keyword) for entry, revision in items],
            "next_cursor": next_cursor}


def get_entry(db: Session, actor: User, scope: ResourceRef, entry_id: UUID) -> dict[str, Any]:
    _authorize(db, actor, scope, "viewer")
    row = db.execute(_current(scope).where(_E.id == entry_id)).one_or_none()
    if row is None:
        raise not_found("时间轴记录不存在")
    return _entry_data(*row, _reply_lookup(db, scope, [row]), _recorded_actors(db, [row]), detail=True)


def get_context(db: Session, actor: User, scope: ResourceRef, entry_id: UUID,
                *, radius: int = 10) -> dict[str, Any]:
    """A bounded newest-first window around a deep-linked timeline entry."""
    _authorize(db, actor, scope, "viewer")
    if type(radius) is not int or not 1 <= radius <= 49:
        raise invalid_request("时间轴上下文每侧须为 1 至 49 条")
    statement = _current(scope)
    anchor = db.execute(statement.where(_E.id == entry_id)).one_or_none()
    if anchor is None:
        raise not_found("时间轴记录不存在")
    happened_at = anchor[0].occurred_at
    newer = db.execute(statement.where(or_(
        _E.occurred_at > happened_at, and_(_E.occurred_at == happened_at, _E.id > entry_id),
    )).order_by(_E.occurred_at, _E.id).limit(radius)).all()
    older = db.execute(statement.where(or_(
        _E.occurred_at < happened_at, and_(_E.occurred_at == happened_at, _E.id < entry_id),
    )).order_by(_E.occurred_at.desc(), _E.id.desc()).limit(radius)).all()
    rows = [*reversed(newer), anchor, *older]
    replies = _reply_lookup(db, scope, rows)
    actors = _recorded_actors(db, rows)
    return {"anchor_id": str(entry_id), "items": [
        _entry_data(entry, revision, replies, actors) for entry, revision in rows
    ]}


def list_revisions(
    db: Session, actor: User, scope: ResourceRef, entry_id: UUID, *,
    cursor: str | None = None, limit: int = 20,
) -> dict[str, Any]:
    _authorize(db, actor, scope, "viewer")
    _entry(db, scope, entry_id)
    _limit(limit)
    cursor_scope = _list_scope("revisions", actor, scope, [str(entry_id)])
    statement = select(_R).where(*_revisions(scope), _R.entry_id == entry_id)
    position = _decode(cursor_scope, cursor)
    if position is not None:
        if len(position) != 1 or type(position[0]) is not int or not 1 <= position[0] <= MAX_VERSION:
            raise invalid_request("无效的时间轴修订游标")
        statement = statement.where(_R.version < position[0])
    rows = db.scalars(statement.order_by(_R.version.desc()).limit(limit + 1)).all()
    items = rows[:limit]
    return {
        "items": [{
            "version": row.version, "kind": row.kind, "body": row.body, "reason": row.reason,
            "actor_id": str(row.actor_id) if row.actor_id else None,
            "created_at": _utc(row.created_at).isoformat(),
        } for row in items],
        "next_cursor": _encode(cursor_scope, [items[-1].version]) if len(rows) > limit else None,
    }
