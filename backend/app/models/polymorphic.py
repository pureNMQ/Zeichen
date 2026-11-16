"""多态表:comment / activity / attachment / reference(§2.2;ADR 0002:实体目标存短码)。

- comment / activity / attachment 的 target 均受 check 约束(可扩展枚举,需迁移)
- reference 的 from/to 同枚举;type 枚举:derives / documents / implements / mentions
- 五类实体(requirement/task/document/directory)的 target_id 存短码(REQ/TASK/DOC/TERM/DIR-n);
  repository/project 目标仍存 UUID;activity 不可变(只记 created_at,无 updated_at / 软删)
"""

import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base,
    CreatedAtMixin,
    CreatedByMixin,
    IdMixin,
    PolymorphicTargetMixin,
    ProjectScopeMixin,
    SoftDeleteMixin,
    TimestampMixin,
)

TARGET_TYPE_VALUES = ("requirement", "task", "document", "repository", "project", "user")
REFERENCE_TYPE_VALUES = ("derives", "documents", "implements", "mentions")


class Comment(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin,
              PolymorphicTargetMixin, Base):
    __tablename__ = "comment"
    __table_args__ = (
        CheckConstraint(
            f"target_type IN {TARGET_TYPE_VALUES}", name="ck_comment_target_type"
        ),
    )

    author_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class Activity(IdMixin, CreatedAtMixin, ProjectScopeMixin, PolymorphicTargetMixin, Base):
    __tablename__ = "activity"
    __table_args__ = (
        CheckConstraint(
            f"target_type IN {TARGET_TYPE_VALUES}", name="ck_activity_target_type"
        ),
    )

    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Attachment(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin,
                 PolymorphicTargetMixin, Base):
    __tablename__ = "attachment"
    __table_args__ = (
        CheckConstraint(
            f"target_type IN {TARGET_TYPE_VALUES}", name="ck_attachment_target_type"
        ),
    )

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Workspace-level user avatars have no project. Other attachment targets
    # continue to require project_id in their service-level validation.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("project.id", ondelete="CASCADE"), nullable=True, index=True
    )


class Reference(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "reference"
    __table_args__ = (
        CheckConstraint(f"from_type IN {TARGET_TYPE_VALUES}", name="ck_reference_from_type"),
        CheckConstraint(f"to_type IN {TARGET_TYPE_VALUES}", name="ck_reference_to_type"),
        CheckConstraint(f"type IN {REFERENCE_TYPE_VALUES}", name="ck_reference_type"),
        CheckConstraint("from_type <> to_type OR from_id <> to_id", name="ck_reference_not_self"),
    )

    from_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    to_type: Mapped[str] = mapped_column(String(32), nullable=False)
    to_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
