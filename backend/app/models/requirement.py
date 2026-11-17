"""requirement / task:状态机(需求六态、任务四态,完全自由流转)+ 项目内短码主键(ADR 0002)。

需求六态:pending / backlog / in_progress / verifying / done / cancelled;
任务四态:backlog / in_progress / done / cancelled。
主键 = (project_id, code):REQ-n / TASK-n,项目内递增、跨项目可同码;
任务必挂需求(requirement_id 存需求短码,复合外键,ADR 0003)。
"""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
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

_CODE_CHECK = "code ~ '^(REQ|TASK)-[1-9][0-9]*$'"


class Requirement(TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "requirement"
    __table_args__ = (
        CheckConstraint(
            f"status IN {REQUIREMENT_STATUS_VALUES}", name="ck_requirement_status"
        ),
        CheckConstraint(
            "description IS NULL OR length(description) <= 512",
            name="ck_requirement_description_length",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(16), primary_key=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
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
        CheckConstraint(f"status IN {TASK_STATUS_VALUES}", name="ck_task_status"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 512",
            name="ck_task_description_length",
        ),
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
    code: Mapped[str] = mapped_column(String(16), primary_key=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="backlog")
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 所属需求短码(REQ-n);必填、可改指向同项目其他需求、禁止置空(ADR 0003)
    requirement_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    requirement: Mapped[Requirement] = relationship(
        back_populates="tasks",
        foreign_keys=[project_id, requirement_id],
        primaryjoin="and_(Requirement.project_id == Task.project_id, Requirement.code == Task.requirement_id)",
        viewonly=True,
    )

    @classmethod
    def has_active_requirement(cls):
        return select(Requirement.code).where(
            Requirement.project_id == cls.project_id,
            Requirement.code == cls.requirement_id,
            Requirement.deleted_at.is_(None),
        ).correlate(cls).exists()


class TaskBlocker(TimestampMixin, CreatedByMixin, Base):
    """任务阻塞依赖边(REQ-7):task_id 被 blocker_id 阻塞(存任务短码,ADR 0002)。

    边行不软删,移除 = 物理删行;(project_id, task_id, blocker_id) 唯一防重复依赖。
    """

    __tablename__ = "task_blocker"
    __table_args__ = (
        UniqueConstraint("project_id", "task_id", "blocker_id", name="uq_task_blocker_pair"),
        ForeignKeyConstraint(
            ["project_id", "task_id"],
            ["task.project_id", "task.code"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "blocker_id"],
            ["task.project_id", "task.code"],
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    task_id: Mapped[str] = mapped_column(String(16), primary_key=True, index=True)
    blocker_id: Mapped[str] = mapped_column(String(16), primary_key=True, index=True)
