"""Explicit notifications shared by one owner and their authorized Agent."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base


class Notification(Base):
    __tablename__ = "v2_notification"
    __table_args__ = (
        UniqueConstraint("project_id", "source_kind", "source_key", "source_version", "owner_id",
                         name="uq_v2_notification_source_owner"),
        ForeignKeyConstraint(
            ["project_id", "source_code", "entry_id"],
            ["v2_timeline_entry.project_id", "v2_timeline_entry.requirement_code", "v2_timeline_entry.id"],
        ),
        CheckConstraint("visibility IN ('shared', 'owner_only')", name="ck_v2_notification_visibility"),
        CheckConstraint("source_version > 0", name="ck_v2_notification_version"),
        CheckConstraint("(read_at IS NULL) = (read_by_id IS NULL)", name="ck_v2_notification_read"),
        CheckConstraint(
            "(source_kind = 'timeline' AND entry_id IS NOT NULL) OR "
            "(source_kind = 'wiki' AND entry_id IS NULL)", name="ck_v2_notification_source",
        ),
        Index("ix_v2_notification_inbox", "owner_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(12), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    source_key: Mapped[str] = mapped_column(String(36), nullable=False)
    source_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_id: Mapped[UUID | None] = mapped_column()
    mentioned_user_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reply_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id"))
