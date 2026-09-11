"""站内通知服务(规格书 §7.2 / frontend-requirements §2.6)。

- 触发源 = activity:所有业务变更记录 activity 后同步生成通知
- 接收者 = 相关成员(无偏好系统):项目 owner / 工作区 admin / 目标的创建者、
  被指派者(task)与参与评论者;排除动作发起者本人
- 通知为接收者本人所有,列表/未读数/已读均只查自己的行
"""

import uuid

from sqlalchemy import delete as sa_delete, func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Activity,
    Comment,
    EntityWatch,
    Notification,
    NotificationPreference,
    Project,
    ProjectMember,
    Requirement,
    Task,
    User,
    WorkspaceMember,
)
from .pagination import page_result
from .permissions import get_team, is_admin, require_project_role

# activity 目标实体 → 可解析创建者/被指派者的模型
_TARGET_CREATED_BY = {
    "requirement": Requirement,
    "task": Task,
    "document": None,  # created_by 直接用 PolymorphicTargetMixin 无;走 _entity_created_by
}

# 全部 activity 都触发通知:project 目标的活动仅 owner/admin 接收(见 _relevant_member_ids)


def _notification_dict(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "target_type": n.target_type,
        "target_id": str(n.target_id),
        "action": n.action,
        "summary": n.summary,
        "actor_id": str(n.actor_id) if n.actor_id else None,
        "read": n.read_at is not None,
        "created_at": n.created_at.isoformat(),
    }


def _relevant_member_ids(db: Session, activity: Activity) -> set[uuid.UUID]:
    """判定相关成员(排除动作发起者):owner/admin + 目标创建者 + 被指派者 + 评论者。"""
    recipients: set[uuid.UUID] = set()

    # 1) 项目 owner(显式 member role=owner)
    owners = db.scalars(
        select(ProjectMember.user_id).where(
            ProjectMember.project_id == activity.project_id,
            ProjectMember.role == "owner",
        )
    ).all()
    recipients.update(owners)

    # 2) 工作区 admin
    team = get_team(db)
    admins = db.scalars(
        select(WorkspaceMember.user_id).where(
            WorkspaceMember.team_id == team.id, WorkspaceMember.role == "admin"
        )
    ).all()
    recipients.update(admins)

    # 3) 目标实体相关者
    if activity.target_type in ("requirement", "task"):
        model = _TARGET_CREATED_BY[activity.target_type]
        obj = db.get(model, activity.target_id)
        if obj is not None:
            if obj.created_by:
                recipients.add(obj.created_by)
            if activity.target_type == "task" and obj.assignee_id:
                recipients.add(obj.assignee_id)
    elif activity.target_type == "project":
        # 项目级活动(记忆)仅 owner/admin 接收,已在上面
        pass
    else:
        # document:创建者来自基类 created_by 列
        from ..models import Document

        obj = db.get(Document, activity.target_id)
        if obj is not None and obj.created_by:
            recipients.add(obj.created_by)

    # 4) 参与评论者
    commenters = db.scalars(
        select(Comment.author_id).where(
            Comment.target_type == activity.target_type,
            Comment.target_id == activity.target_id,
            Comment.deleted_at.is_(None),
        )
    ).all()
    recipients.update(commenters)

    recipients.discard(activity.actor_id)
    recipients.discard(None)
    return recipients


def notify_activity(db: Session, activity: Activity) -> None:
    """activity 落地后为相关成员生成通知(不 commit,随调用方事务一起提交)。"""
    if activity.actor_id is None:
        return
    recipients = _filter_by_preferences(db, activity, _relevant_member_ids(db, activity))
    for user_id in recipients:
        db.add(
            Notification(
                project_id=activity.project_id,
                user_id=user_id,
                actor_id=activity.actor_id,
                target_type=activity.target_type,
                target_id=activity.target_id,
                action=activity.action,
                summary=activity.summary,
            )
        )


def list_notifications(
    db: Session, user: User, cursor: str | None, limit: int, unread_only: bool = False
) -> dict:
    from .pagination import decode_cursor

    filters = {"unread": unread_only}
    offset = decode_cursor(filters, cursor)
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = db.scalars(stmt.order_by(Notification.created_at.desc()).offset(offset).limit(limit)).all()
    items = [_notification_dict(n) for n in rows]
    return page_result(items, offset, limit, filters)


def unread_count(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ) or 0


def mark_read(db: Session, user: User, notification_id: uuid.UUID) -> None:
    from datetime import datetime, timezone

    n = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if n is None:
        from ..errors import not_found

        raise not_found("通知不存在")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()


def mark_all_read(db: Session, user: User) -> None:
    from datetime import datetime, timezone

    rows = db.scalars(
        select(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    ).all()
    now = datetime.now(timezone.utc)
    for n in rows:
        n.read_at = now
    db.commit()


# ---- 通知偏好与实体级关注(REQ 023b607e) ----

NOTIFICATION_DOMAINS = ("requirement", "task", "document", "project")
NOTIFICATION_ACTIONS = (
    "create", "update", "status", "comment", "reference",
    "assign", "claim", "delete", "restore", "move",
)


def get_preferences(db: Session, user: User) -> dict:
    """返回三段偏好状态:域与动作缺省全开,仅显式关闭的为 False。"""
    rows = db.scalars(
        select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    ).all()
    domains = {key: True for key in NOTIFICATION_DOMAINS}
    actions = {key: True for key in NOTIFICATION_ACTIONS}
    for row in rows:
        if row.scope_type == "domain" and row.scope_key in domains:
            domains[row.scope_key] = row.enabled
        elif row.scope_type == "action" and row.scope_key in actions:
            actions[row.scope_key] = row.enabled
    return {"domains": domains, "actions": actions}


def update_preferences(db: Session, user: User, domains: dict[str, bool], actions: dict[str, bool]) -> dict:
    """整体替换式更新:未知键拒绝;键缺失视为保持开启(删除该行)。"""
    unknown = (set(domains) - set(NOTIFICATION_DOMAINS)) | (set(actions) - set(NOTIFICATION_ACTIONS))
    if unknown:
        from ..errors import invalid_request

        raise invalid_request(f"未知的偏好项: {sorted(unknown)}")
    rows = db.scalars(
        select(NotificationPreference).where(NotificationPreference.user_id == user.id)
    ).all()
    by_key = {(r.scope_type, r.scope_key): r for r in rows}
    desired: list[tuple[str, str, bool]] = [
        ("domain", key, enabled) for key, enabled in domains.items()
    ] + [
        ("action", key, enabled) for key, enabled in actions.items()
    ]
    for scope_type, key, enabled in desired:
        row = by_key.get((scope_type, key))
        if enabled:
            if row is not None:
                db.delete(row)
            continue
        if row is not None:
            row.enabled = False
            continue
        db.add(NotificationPreference(user_id=user.id, scope_type=scope_type, scope_key=key, enabled=False))
    db.commit()
    return get_preferences(db, user)


def is_watching(db: Session, user: User, target_type: str, target_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(EntityWatch.id).where(
                EntityWatch.user_id == user.id,
                EntityWatch.target_type == target_type,
                EntityWatch.target_id == target_id,
            )
        )
        is not None
    )


def watch_entity(db: Session, user: User, target_type: str, target_id: uuid.UUID) -> None:
    from .polymorphic import resolve_target

    project = resolve_target(db, target_type, target_id)
    require_project_role(db, user.id, project.id, min_level="viewer")
    if not is_watching(db, user, target_type, target_id):
        db.add(EntityWatch(project_id=project.id, user_id=user.id, target_type=target_type, target_id=target_id))
        db.commit()


def unwatch_entity(db: Session, user: User, target_type: str, target_id: uuid.UUID) -> None:
    db.execute(
        sa_delete(EntityWatch).where(
            EntityWatch.user_id == user.id,
            EntityWatch.target_type == target_type,
            EntityWatch.target_id == target_id,
        )
    )
    db.commit()


def _filter_by_preferences(
    db: Session, activity: Activity, recipients: set[uuid.UUID]
) -> set[uuid.UUID]:
    """偏好只收窄:关闭了该域/动作的成员不再接收;实体级关注突破收窄。"""
    if not recipients:
        return recipients
    watchers = set(
        db.scalars(
            select(EntityWatch.user_id).where(
                EntityWatch.target_type == activity.target_type,
                EntityWatch.target_id == activity.target_id,
            )
        ).all()
    )
    rows = db.scalars(
        select(NotificationPreference).where(
            NotificationPreference.user_id.in_(recipients),
            NotificationPreference.enabled.is_(False),
        )
    ).all()
    disabled: set[uuid.UUID] = set()
    for row in rows:
        if row.scope_type == "domain" and row.scope_key == activity.target_type:
            disabled.add(row.user_id)
        elif row.scope_type == "action" and row.scope_key == activity.action:
            disabled.add(row.user_id)
    return {user_id for user_id in recipients if user_id in watchers or user_id not in disabled}
