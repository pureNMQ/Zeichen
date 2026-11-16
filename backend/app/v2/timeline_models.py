"""Project-scoped timeline entries and append-only manual revisions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base


class TimelineEntry(Base):
    __tablename__ = "v2_timeline_entry"
    __table_args__ = (
        UniqueConstraint("project_id", "requirement_code", "id", name="uq_v2_timeline_entry_scope"),
        ForeignKeyConstraint(["project_id", "requirement_code"], ["requirement.project_id", "requirement.code"]),
        ForeignKeyConstraint(["project_id", "source_task_code"], ["task.project_id", "task.code"]),
        ForeignKeyConstraint(
            ["project_id", "requirement_code", "reply_to_id"],
            ["v2_timeline_entry.project_id", "v2_timeline_entry.requirement_code", "v2_timeline_entry.id"],
        ),
        CheckConstraint("reply_to_id IS NULL OR reply_to_id <> id", name="ck_v2_timeline_no_self_reply"),
        CheckConstraint(
            "(kind = 'manual' AND latest_version IS NOT NULL AND latest_version > 0 AND event_type IS NULL) OR "
            "(kind = 'system' AND latest_version IS NULL AND event_type IS NOT NULL AND reply_to_id IS NULL)",
            name="ck_v2_timeline_entry_kind",
        ),
        Index("ix_v2_timeline_entry_order", "project_id", "requirement_code", "occurred_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    requirement_code: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    source_task_code: Mapped[str | None] = mapped_column(String(16))
    reply_to_id: Mapped[UUID | None] = mapped_column()
    latest_version: Mapped[int | None] = mapped_column()
    event_type: Mapped[str | None] = mapped_column(String(64))
    event_data: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))


class TimelineRevision(Base):
    __tablename__ = "v2_timeline_revision"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "requirement_code", "entry_id"],
            ["v2_timeline_entry.project_id", "v2_timeline_entry.requirement_code", "v2_timeline_entry.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(version = 1 AND kind = 'create' AND body IS NOT NULL) OR "
            "(version > 1 AND ((kind = 'revise' AND body IS NOT NULL) OR "
            "(kind = 'withdraw' AND body IS NULL)))",
            name="ck_v2_timeline_revision_kind",
        ),
    )

    entry_id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    requirement_code: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String(512))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
