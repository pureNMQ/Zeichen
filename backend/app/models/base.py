"""SQLAlchemy 公共基类与 mixin。

规格书 §2.1 五件套约定:created_at / updated_at / created_by / project_id / deleted_at + UUID 主键。
工作区级实体(user / team / api_key / workspace_member / memory_grant)不带 project_id,
它们是 workspace 根,project_id 无意义——在 ticket 01 Answer 中记录此判定。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CreatedAtMixin:
    """不可变审计表(activity)只用 created_at。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreatedByMixin:
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )


class ProjectScopeMixin:
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )


class PolymorphicTargetMixin:
    """多态目标:target_type 枚举 + target_id,check 约束见各表。"""

    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)


__all__ = [
    "Base",
    "IdMixin",
    "TimestampMixin",
    "CreatedAtMixin",
    "SoftDeleteMixin",
    "CreatedByMixin",
    "ProjectScopeMixin",
    "PolymorphicTargetMixin",
]
