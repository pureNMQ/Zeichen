"""Wiki and glossary documents(复合主键 (project_id, code),ADR 0002:DOC/TERM/DIR 短码)。"""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin

DOC_TYPE_VALUES = ("wiki", "glossary")


class Document(TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint(f"doc_type IN {DOC_TYPE_VALUES}", name="ck_document_doc_type"),
        # 同表父子:复合外键 (project_id, parent_id) → document(project_id, code)
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["document.project_id", "document.code"],
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["project_id", "directory_id"],
            ["document_directory.project_id", "document_directory.code"],
            ondelete="SET NULL",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(16), primary_key=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 父 Wiki / 所属词典目录的短码(DOC-n / DIR-n);根级为 NULL
    parent_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    directory_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    versions: Mapped[list["DocumentVersion"]] = relationship(
        primaryjoin="and_(Document.project_id == DocumentVersion.project_id, Document.code == DocumentVersion.document_id)",
        foreign_keys="[DocumentVersion.project_id, DocumentVersion.document_id]",
        order_by="DocumentVersion.version_no",
        viewonly=True,
    )


class DocumentDirectory(TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    """Persistent organization for glossary terms only(DIR-n 短码)."""

    __tablename__ = "document_directory"
    __table_args__ = (
        CheckConstraint("module_type IN ('glossary')", name="ck_document_directory_module_type"),
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["document_directory.project_id", "document_directory.code"],
            ondelete="SET NULL",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), primary_key=True
    )
    code: Mapped[str] = mapped_column(String(16), primary_key=True)

    module_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)


class DocumentVersion(IdMixin, TimestampMixin, CreatedByMixin, Base):
    """版本行维持 UUID 主键(ADR 0002 §2);(project_id, document_id) 复合引用所属文档短码。"""

    __tablename__ = "document_version"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="ck_document_version_no_positive"),
        UniqueConstraint("project_id", "document_id", "version_no", name="uq_document_version_doc_no"),
        ForeignKeyConstraint(
            ["project_id", "document_id"],
            ["document.project_id", "document.code"],
            ondelete="CASCADE",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 所属文档短码(DOC-n / TERM-n)
    document_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[Document] = relationship(
        primaryjoin="and_(Document.project_id == DocumentVersion.project_id, Document.code == DocumentVersion.document_id)",
        foreign_keys="[Document.project_id, Document.code]",
        viewonly=True,
    )
