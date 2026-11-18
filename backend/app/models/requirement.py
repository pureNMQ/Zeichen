"""requirement / task:状态机(需求六态、任务四态,完全自由流转)+ 项目内短码主键(ADR 0002)。

需求六态:pending / backlog / in_progress / verifying / done / cancelled;
任务四态:backlog / in_progress / done / cancelled。
主键 = (project_id, code):REQ-n / REQ-n-Tm,任务在所属需求内编号;
任务必挂需求(requirement_id 存需求短码,复合外键,ADR 0003)。
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, SoftDeleteMixin, TimestampMixin


REQUIREMENT_STATUS_VALUES = (
    "pending",
    "backlog",
    "in_progress",
    "verifying",
    "done",
    "cancelled",
)
TASK_STATUS_VALUES = ("backlog", "in_progress", "done", "cancelled")



class Requirement(TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "requirement"
    __table_args__ = (
        CheckConstraint(
            f"status IN {REQUIREMENT_STATUS_VALUES}", name="ck_requirement_status"
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(16), primary_key=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))

    tasks: Mapped[list["Task"]] = relationship(
        back_populates="requirement",
        foreign_keys="Task.requirement_id",
        primaryjoin="and_(Requirement.project_id == Task.project_id, Requirement.code == Task.requirement_id)",
    )


class Task(TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        UniqueConstraint("project_id", "legacy_code", name="uq_task_legacy_code"),
        CheckConstraint("code LIKE requirement_id || '-T_%'", name="ck_task_code_parent"),
        CheckConstraint(f"status IN {TASK_STATUS_VALUES}", name="ck_task_status"),

        # 任务必挂需求:复合外键 (project_id, requirement_id) → requirement(project_id, code)
        ForeignKeyConstraint(
            ["project_id", "requirement_id"],
            ["requirement.project_id", "requirement.code"],
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(36), primary_key=True)
    legacy_code: Mapped[str | None] = mapped_column(String(16))

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="backlog")
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 所属需求短码(REQ-n);创建后不可更改
    requirement_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    requirement: Mapped[Requirement] = relationship(
        back_populates="tasks",
        foreign_keys=[project_id, requirement_id],
        primaryjoin="and_(Requirement.project_id == Task.project_id, Requirement.code == Task.requirement_id)",
        viewonly=True,
    )

    @classmethod
    def matches_code(cls, code: str):
        """Resolve a task code (including a migrated alias) in a project-scoped query."""
        field = cls.legacy_code if code.startswith("TASK-") else cls.code
        return field == code

    @classmethod
    def has_active_requirement(cls):
        return select(Requirement.code).where(
            Requirement.project_id == cls.project_id,
            Requirement.code == cls.requirement_id,
            Requirement.deleted_at.is_(None),
        ).correlate(cls).exists()
