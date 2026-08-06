"""Wiki and glossary documents.

Code API reference has its own aggregate in ``code_reference.py`` and is not a
document subtype.
"""

import uuid

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, ProjectScopeMixin, SoftDeleteMixin, TimestampMixin

DOC_TYPE_VALUES = ("wiki", "glossary")


class Document(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "document"
    __table_args__ = (CheckConstraint(f"doc_type IN {DOC_TYPE_VALUES}", name="ck_document_doc_type"),)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document.id", ondelete="SET NULL"), nullable=True, index=True)
    directory_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_directory.id", ondelete="SET NULL"), nullable=True, index=True)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document", order_by="DocumentVersion.version_no")


class DocumentDirectory(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    """Persistent organization for glossary terms only."""

    __tablename__ = "document_directory"
    __table_args__ = (CheckConstraint("module_type IN ('glossary')", name="ck_document_directory_module_type"),)

    module_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_directory.id", ondelete="SET NULL"), nullable=True, index=True)


class DocumentVersion(IdMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "document_version"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="ck_document_version_no_positive"),
        UniqueConstraint("document_id", "version_no", name="uq_document_version_doc_no"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[Document] = relationship(back_populates="versions")
