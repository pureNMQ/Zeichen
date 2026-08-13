"""Durable, workspace-scoped Cognee restart jobs."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


COGNEE_RESTART_JOB_STATUSES = ("queued", "running", "completed", "failed")


class CogneeRestartJob(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "cognee_restart_job"
    __table_args__ = (
        CheckConstraint(
            f"status IN {COGNEE_RESTART_JOB_STATUSES}", name="ck_cognee_restart_job_status"
        ),
        Index(
            "uq_cognee_restart_job_active_team",
            "team_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("team.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
