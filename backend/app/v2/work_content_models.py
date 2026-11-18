"""Immutable requirement and task content snapshots and their Markdown links."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, CreatedAtMixin, CreatedByMixin


class WorkVersion(CreatedAtMixin, CreatedByMixin, Base):
    __tablename__ = "v2_work_version"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "requirement_code"], ["requirement.project_id", "requirement.code"], ondelete="CASCADE"),
        ForeignKeyConstraint(["project_id", "task_code"], ["task.project_id", "task.code"], ondelete="CASCADE"),
        CheckConstraint("version > 0 AND ((task_code IS NULL AND code = requirement_code) OR (task_code IS NOT NULL AND code = task_code))", name="ck_work_version_subject"),
    )

    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    requirement_code: Mapped[str] = mapped_column(String(16))
    task_code: Mapped[str | None] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)


class WorkReference(Base):
    __tablename__ = "v2_work_reference"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "code", "version"],
                             ["v2_work_version.project_id", "v2_work_version.code", "v2_work_version.version"], ondelete="CASCADE"),
        Index("ix_work_reference_target", "project_id", "target_kind", "target_id"),
    )
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), primary_key=True)
