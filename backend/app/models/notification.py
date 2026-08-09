"""站内通知(规格书 §7.2 / frontend-requirements §2.6)。

- 轻量:未读数 + 列表 + 点击跳转;触发源 = activity
- 接收者 = 相关成员(无偏好系统):项目 owner / 工作区 admin / 实体的创建者、
  被指派者与参与评论者;排除动作发起者本人
- read_at 表示已读;通知不参与软删(规格书未要求恢复通知)
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
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
