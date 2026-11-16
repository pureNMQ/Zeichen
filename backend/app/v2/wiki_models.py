"""Current Wiki documents, immutable snapshots, and their reference index."""

from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..models.base import Base, CreatedAtMixin, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin


class WikiFields:
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    body: Mapped[str] = mapped_column(Text, nullable=False)


class Wiki(WikiFields, TimestampMixin, CreatedByMixin, SoftDeleteMixin, Base):
    __tablename__ = "v2_wiki"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "parent_id"], ["v2_wiki.project_id", "v2_wiki.code"]),
        CheckConstraint("version_no > 0", name="ck_v2_wiki_version_positive"),
        Index("ix_v2_wiki_parent", "project_id", "parent_id"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(String(16))
    version_no: Mapped[int] = mapped_column(nullable=False)
    deleted_by: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))


class WikiVersion(WikiFields, IdMixin, CreatedAtMixin, CreatedByMixin, Base):
    __tablename__ = "v2_wiki_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "wiki_code"], ["v2_wiki.project_id", "v2_wiki.code"], ondelete="CASCADE",
        ),
        UniqueConstraint("project_id", "wiki_code", "version_no", name="uq_v2_wiki_version"),
        CheckConstraint("version_no > 0", name="ck_v2_wiki_snapshot_version_positive"),
    )

    project_id: Mapped[UUID] = mapped_column(nullable=False)
    wiki_code: Mapped[str] = mapped_column(String(16), nullable=False)
    version_no: Mapped[int] = mapped_column(nullable=False)


class WikiReference(Base):
    """Index by snapshot. A dangling target remains addressable if later restored."""

    __tablename__ = "v2_wiki_reference"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "wiki_code", "version_no"],
            ["v2_wiki_version.project_id", "v2_wiki_version.wiki_code", "v2_wiki_version.version_no"],
            ondelete="CASCADE",
        ),
        Index("ix_v2_wiki_reference_target", "project_id", "target_kind", "target_id"),
    )

    project_id: Mapped[UUID] = mapped_column(primary_key=True)
    wiki_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    version_no: Mapped[int] = mapped_column(primary_key=True)
    target_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), primary_key=True)
