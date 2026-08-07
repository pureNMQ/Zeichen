"""Durable, project-scoped asynchronous Cognee improve jobs."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin


MEMORY_IMPROVE_JOB_STATUSES = (
    "queued",
    "running",
    "completed",
    "failed",
    "upstream_busy",
    "timed_out",
    "unknown",
)


class MemoryImproveJob(IdMixin, CreatedAtMixin, Base):
    """One requested distillation, owned by a durable worker rather than an MCP call."""

    __tablename__ = "memory_improve_job"
    __table_args__ = (
        CheckConstraint(
            f"status IN {MEMORY_IMPROVE_JOB_STATUSES}",
            name="ck_memory_improve_job_status",
        ),
        Index(
            "uq_memory_improve_job_active_session",
            "project_id",
            "target_agent_id",
            "session_id",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    result: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
