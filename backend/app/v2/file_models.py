"""Project file identities and short-lived read grants."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, CreatedAtMixin, CreatedByMixin, SoftDeleteMixin, TimestampMixin


class ProjectFile(TimestampMixin, CreatedByMixin, SoftDeleteMixin, Base):
    __tablename__ = "v2_project_file"
    __table_args__ = (
        CheckConstraint("size > 0", name="ck_v2_project_file_size_positive"),
        Index("ix_v2_project_file_created", "project_id", "created_at", "id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deleted_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))


class FileAssociation(CreatedAtMixin, CreatedByMixin, Base):
    """Explicit usage, independent from Markdown and the file's storage lifecycle."""

    __tablename__ = "v2_file_association"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "file_id"], ["v2_project_file.project_id", "v2_project_file.id"], ondelete="CASCADE",
        ),
        CheckConstraint("target_kind IN ('project', 'requirements', 'tasks', 'wiki', 'timeline')",
                        name="ck_v2_file_association_target_kind"),
        Index("ix_v2_file_association_target", "project_id", "target_kind", "target_id"),
    )

    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    file_id: Mapped[UUID] = mapped_column(primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class FileGrant(CreatedAtMixin, Base):
    __tablename__ = "v2_file_grant"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "file_id"], ["v2_project_file.project_id", "v2_project_file.id"], ondelete="CASCADE",
        ),
        Index("ix_v2_file_grant_file", "project_id", "file_id"),
        Index("ix_v2_file_grant_expiry", "expires_at"),
    )

    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(nullable=False)
    file_id: Mapped[UUID] = mapped_column(nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    api_key_id: Mapped[UUID | None] = mapped_column(ForeignKey("api_key.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inline: Mapped[bool] = mapped_column(nullable=False)
