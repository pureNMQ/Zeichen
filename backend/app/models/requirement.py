"""requirement / task:状态机(需求六态、任务四态,完全自由流转)。

需求六态:pending / backlog / in_progress / verifying / done / cancelled(验收上移需求,ADR 0003);
任务四态:backlog / in_progress / done / cancelled(verifying 已删)。
check 约束保证状态值合法;流转规则在 service 层(workflow.py)。
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, ProjectScopeMixin, SoftDeleteMixin, TimestampMixin

REQUIREMENT_STATUS_VALUES = (
    "pending",
    "backlog",
    "in_progress",
    "verifying",
    "done",
    "cancelled",
)
TASK_STATUS_VALUES = ("backlog", "in_progress", "done", "cancelled")


class Requirement(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
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

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    tasks: Mapped[list["Task"]] = relationship(back_populates="requirement")


class Task(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUS_VALUES}", name="ck_task_status"),
        CheckConstraint(
            "description IS NULL OR length(description) <= 512",
            name="ck_task_description_length",
        ),
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="backlog")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 派生任务溯源;任务必须挂需求(ADR 0003,不再有独立任务)
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirement.id", ondelete="CASCADE"), nullable=False, index=True
    )

    requirement: Mapped[Requirement] = relationship(back_populates="tasks")


class TaskBlocker(IdMixin, TimestampMixin, CreatedByMixin, ProjectScopeMixin, Base):
    """任务阻塞依赖边(REQ-7):task_id 被 blocker_id 阻塞。

    边行不软删,移除 = 物理删行;(task_id, blocker_id) 唯一防重复依赖。
    """

    __tablename__ = "task_blocker"
    __table_args__ = (
        UniqueConstraint("task_id", "blocker_id", name="uq_task_blocker_pair"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
    blocker_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("task.id", ondelete="CASCADE"), nullable=False, index=True
    )
