"""Independent code API reference aggregates.

Code symbols are not documents.  A symbol owns its structured declaration and
version history; enum items are rows owned by an enum, not symbols themselves.
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, ProjectScopeMixin, SoftDeleteMixin, TimestampMixin

CODE_SYMBOL_KINDS = (
    "class", "struct", "interface", "enum", "function", "constructor", "method", "field", "property", "constant",
)


class CodeLibrary(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, ProjectScopeMixin, Base):
    __tablename__ = "code_library"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    package: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbols: Mapped[list["CodeSymbol"]] = relationship(back_populates="library", cascade="all, delete-orphan")


class CodeSymbol(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "code_symbol"
    __table_args__ = (CheckConstraint(f"kind IN {CODE_SYMBOL_KINDS}", name="ck_code_symbol_kind"),)

    library_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("code_library.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_symbol_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("code_symbol.id", ondelete="CASCADE"), nullable=True, index=True)
    namespace: Mapped[str | None] = mapped_column(String(256), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    remarks: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accessibility: Mapped[str] = mapped_column(String(32), nullable=False, default="public")
    source_declaration: Mapped[str | None] = mapped_column(Text, nullable=True)
    since_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # This is a discriminated, service-validated declaration payload, not free-form document metadata.
    definition: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    library: Mapped[CodeLibrary] = relationship(back_populates="symbols")
    owner: Mapped["CodeSymbol | None"] = relationship(remote_side="CodeSymbol.id", back_populates="children")
    children: Mapped[list["CodeSymbol"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    enum_members: Mapped[list["EnumMember"]] = relationship(back_populates="enum", cascade="all, delete-orphan", order_by="EnumMember.position")
    versions: Mapped[list["CodeSymbolVersion"]] = relationship(back_populates="symbol", cascade="all, delete-orphan", order_by="CodeSymbolVersion.revision")


class EnumMember(IdMixin, Base):
    __tablename__ = "code_enum_member"
    __table_args__ = (UniqueConstraint("enum_id", "position", name="uq_code_enum_member_position"), UniqueConstraint("enum_id", "name", name="uq_code_enum_member_name"))

    enum_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("code_symbol.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    assigned_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enum: Mapped[CodeSymbol] = relationship(back_populates="enum_members")


class CodeSymbolVersion(IdMixin, CreatedByMixin, Base):
    __tablename__ = "code_symbol_version"
    __table_args__ = (UniqueConstraint("symbol_id", "revision", name="uq_code_symbol_version_revision"),)

    symbol_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("code_symbol.id", ondelete="CASCADE"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    symbol: Mapped[CodeSymbol] = relationship(back_populates="versions")
