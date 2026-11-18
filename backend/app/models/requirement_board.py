from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RequirementBlocker(Base):
    __tablename__ = "requirement_blocker"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "requirement_code"], ["requirement.project_id", "requirement.code"], ondelete="CASCADE"),
        ForeignKeyConstraint(["project_id", "blocker_code"], ["requirement.project_id", "requirement.code"], ondelete="CASCADE"),
        CheckConstraint("requirement_code <> blocker_code", name="ck_requirement_blocker_not_self"),
        Index("ix_requirement_blocker_reverse", "project_id", "blocker_code"),
    )
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    requirement_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    blocker_code: Mapped[str] = mapped_column(String(16), primary_key=True)


class RequirementAssigneeHistory(Base):
    """Retain actual assigned identities after reassignment, without guessing from display names."""

    __tablename__ = "requirement_assignee_history"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "requirement_code"], ["requirement.project_id", "requirement.code"], ondelete="CASCADE"),
    )
    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    requirement_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
