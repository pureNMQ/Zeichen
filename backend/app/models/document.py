"""document / document_version:文档三子模块一表(§2.2)。

doc_type: wiki / glossary / api;差异进 metadata JSON。
version 链只追加、不软删(全文版本链,回滚 = 重建 content + 新版本)。
"""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, ProjectScopeMixin, SoftDeleteMixin, TimestampMixin

DOC_TYPE_VALUES = ("wiki", "glossary", "api")


class Document(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "document"
    __table_args__ = (CheckConstraint(f"doc_type IN {DOC_TYPE_VALUES}", name="ck_document_doc_type"),)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Wiki 的父子结构；词典/API 的组织位置使用 directory_id，二者由 service 层按模块隔离校验。
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document.id", ondelete="SET NULL"), nullable=True, index=True
    )
    directory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document_directory.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # 列名 metadata(规格书 §2.2);metadata 为 Declarative 保留名,属性用 doc_metadata
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", order_by="DocumentVersion.version_no"
    )


class DocumentDirectory(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    """词典/API 的持久化目录；它不是 Document，不能版本化或被引用。"""

    __tablename__ = "document_directory"
    __table_args__ = (
        CheckConstraint("module_type IN ('glossary', 'api')", name="ck_document_directory_module_type"),
    )

    module_type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document_directory.id", ondelete="SET NULL"), nullable=True, index=True
    )


class DocumentVersion(IdMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "document_version"
    __table_args__ = (
        CheckConstraint("version_no > 0", name="ck_document_version_no_positive"),
        UniqueConstraint("document_id", "version_no", name="uq_document_version_doc_no"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")
