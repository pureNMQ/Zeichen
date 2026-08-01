"""requirement / task:五态状态机(§3.1 / §3.2)。

状态:backlog → in_progress → verifying → done,侧路 cancelled。
check 约束保证状态值合法;状态机流转规则在 service 层(05+ 票)。
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, ProjectScopeMixin, SoftDeleteMixin, TimestampMixin

WORKFLOW_STATUS_VALUES = ("backlog", "in_progress", "verifying", "done", "cancelled")


class Requirement(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "requirement"
    __table_args__ = (
        CheckConstraint(
            f"status IN {WORKFLOW_STATUS_VALUES}", name="ck_requirement_status"
        ),
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="backlog")

    tasks: Mapped[list["Task"]] = relationship(back_populates="requirement")


class Task(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "task"
    __table_args__ = (
        CheckConstraint(f"status IN {WORKFLOW_STATUS_VALUES}", name="ck_task_status"),
    )

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="backlog")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 派生任务溯源;独立任务可空(§2.3)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("requirement.id", ondelete="SET NULL"), nullable=True, index=True
    )

    requirement: Mapped[Requirement | None] = relationship(back_populates="tasks")
