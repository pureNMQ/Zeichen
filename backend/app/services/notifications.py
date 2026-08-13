"""站内通知服务(规格书 §7.2 / frontend-requirements §2.6)。

- 触发源 = activity:所有业务变更记录 activity 后同步生成通知
- 接收者 = 相关成员(无偏好系统):项目 owner / 工作区 admin / 目标的创建者、
  被指派者(task)与参与评论者;排除动作发起者本人
- 通知为接收者本人所有,列表/未读数/已读均只查自己的行
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import (
    Activity,
    Comment,
    Notification,
    Project,
    ProjectMember,
    Requirement,
    Task,
    User,
    WorkspaceMember,
)
from .pagination import page_result
from .permissions import get_team, is_admin

# activity 目标实体 → 可解析创建者/被指派者的模型
_TARGET_CREATED_BY = {
    "requirement": Requirement,
    "task": Task,
    "document": None,  # created_by 直接用 PolymorphicTargetMixin 无;走 _entity_created_by
    "code_symbol": None,
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
        # document / code_symbol:创建者来自基类 created_by 列
        from ..models import CodeSymbol, Document

        model = Document if activity.target_type == "document" else CodeSymbol
        obj = db.get(model, activity.target_id)
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
    recipients = _relevant_member_ids(db, activity)
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
