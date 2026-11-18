"""站内通知(规格书 §7.2 / frontend-requirements §2.6)。

- 轻量:未读数 + 列表 + 点击跳转;触发源 = activity
- 接收者 = 相关成员(无偏好系统):项目 owner / 工作区 admin / 实体的创建者、
  被指派者与参与评论者;排除动作发起者本人
- read_at 表示已读;通知不参与软删(规格书未要求恢复通知)
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, PolymorphicTargetMixin, ProjectScopeMixin, TimestampMixin


class Notification(IdMixin, TimestampMixin, ProjectScopeMixin, PolymorphicTargetMixin, Base):
    __tablename__ = "notification"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class NotificationPreference(IdMixin, TimestampMixin, Base):
    """用户级通知偏好(REQ 023b607e):仅记录「关闭」的组合,缺省为开启。

    scope_type = 'domain' 时 scope_key 为实体类型(requirement/task/document/project);
    scope_type = 'action' 时 scope_key 为动作词(create/status/comment/...)。
    偏好只做收窄过滤,不做扩大;实体级关注(EntityWatch)可突破收窄。
    """

    __tablename__ = "notification_preference"
    __table_args__ = (
        UniqueConstraint("user_id", "scope_type", "scope_key", name="uq_notif_pref_user_scope"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EntityWatch(IdMixin, TimestampMixin, ProjectScopeMixin, PolymorphicTargetMixin, Base):
    """实体级关注(REQ 023b607e):关注的实体变更始终通知,不受域/动作收窄影响。"""

    __tablename__ = "entity_watch"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", "target_type", "target_id", name="uq_entity_watch_user_target"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
