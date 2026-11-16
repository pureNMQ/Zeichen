"""Wiki documents(复合主键 (project_id, code),ADR 0002:DOC/TERM 短码)。

REQ-59:glossary 合并进 wiki——doc_type 仅剩 'wiki',TERM-n 短码按「永不改变」原则保留;
DocumentDirectory 废弃(生产实测零使用);新增 doc_link 表承载 [[双链]](断链行保留:to_code 为空)。
"""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin

DOC_TYPE_VALUES = ("wiki",)
# 单元素元组会渲染成非法的 IN ('wiki',),显式展开
_DOC_TYPE_CHECK = "doc_type IN ('wiki')"


class Document(TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint(_DOC_TYPE_CHECK, name="ck_document_doc_type"),
        # 同表父子:复合外键 (project_id, parent_id) → document(project_id, code)
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["document.project_id", "document.code"],
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
    # 父 Wiki 短码(DOC-n / 历史 TERM-n);根级为 NULL
    parent_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    versions: Mapped[list["DocumentVersion"]] = relationship(
        primaryjoin="and_(Document.project_id == DocumentVersion.project_id, Document.code == DocumentVersion.document_id)",
        foreign_keys="[DocumentVersion.project_id, DocumentVersion.document_id]",
        order_by="DocumentVersion.version_no",
        viewonly=True,
    )


class DocLink(IdMixin, TimestampMixin, Base):
    """[[双链]]行(REQ-59 W1/D5):写入时解析正文落表。

    - from_code:链接所在文档短码(复合外键级联删除);
    - to_code:解析命中的目标短码;断链(目标不存在/同名多义)为 NULL 且 raw_text 保留原文;
    - 一条正文链接一行;文档保存/回滚时整表替换其 from 行;
    - 查询:正向(outgoing)= where from_code=doc;反向(incoming)= where to_code=doc。
    """

    __tablename__ = "doc_link"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "from_code"],
            ["document.project_id", "document.code"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "to_code"],
            ["document.project_id", "document.code"],
            ondelete="CASCADE",
        ),
        Index("ix_doc_link_reverse", "project_id", "to_code"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    to_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 链接原文:目标部分(短码或标题,不含显示文本、不含 #小节)
    raw_text: Mapped[str] = mapped_column(String(256), nullable=False)
    display_text: Mapped[str | None] = mapped_column(String(256), nullable=True)
    section: Mapped[str | None] = mapped_column(String(256), nullable=True)

    document: Mapped[Document] = relationship(
        primaryjoin="and_(Document.project_id == DocLink.project_id, Document.code == DocLink.from_code)",
        foreign_keys="[DocLink.project_id, DocLink.from_code]",
        viewonly=True,
    )


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
    # 所属文档短码(DOC-n / 历史 TERM-n)
    document_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[Document] = relationship(
        primaryjoin="and_(Document.project_id == DocumentVersion.project_id, Document.code == DocumentVersion.document_id)",
        foreign_keys="[DocumentVersion.project_id, DocumentVersion.document_id]",
        viewonly=True,
    )
