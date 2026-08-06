"""Add structured program-library symbols to API documents.

Revision ID: 0805libsymbols
Revises: 0420docworkbench
Create Date: 2026-08-05 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0805libsymbols"
down_revision: Union[str, None] = "0420docworkbench"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "library_symbol",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=False),
        sa.Column("package", sa.String(length=256), nullable=False),
        sa.Column("namespace", sa.String(length=256), nullable=True),
        sa.Column("symbol", sa.String(length=256), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=True),
        sa.Column("canonical_signature", sa.Text(), nullable=False),
        sa.Column("return_type", sa.String(length=512), nullable=True),
        sa.Column("return_description", sa.Text(), nullable=True),
        sa.Column("since_version", sa.String(length=64), nullable=True),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('class', 'struct', 'interface', 'enum', 'function', 'method', 'property', 'constant')", name="ck_library_symbol_kind"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_symbol_id"], ["library_symbol.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.create_index("ix_library_symbol_document_id", "library_symbol", ["document_id"])
    op.create_index("ix_library_symbol_owner_symbol_id", "library_symbol", ["owner_symbol_id"])
    op.create_table(
        "library_symbol_parameter",
        sa.Column("symbol_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("type_name", sa.String(length=512), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("default_value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["library_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", "position", name="uq_library_symbol_parameter_position"),
    )
    op.create_index("ix_library_symbol_parameter_symbol_id", "library_symbol_parameter", ["symbol_id"])
    op.create_table(
        "library_symbol_exception",
        sa.Column("symbol_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type_name", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["symbol_id"], ["library_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", "position", name="uq_library_symbol_exception_position"),
    )
    op.create_index("ix_library_symbol_exception_symbol_id", "library_symbol_exception", ["symbol_id"])


def downgrade() -> None:
    op.drop_index("ix_library_symbol_exception_symbol_id", table_name="library_symbol_exception")
    op.drop_table("library_symbol_exception")
    op.drop_index("ix_library_symbol_parameter_symbol_id", table_name="library_symbol_parameter")
    op.drop_table("library_symbol_parameter")
    op.drop_index("ix_library_symbol_owner_symbol_id", table_name="library_symbol")
    op.drop_index("ix_library_symbol_document_id", table_name="library_symbol")
    op.drop_table("library_symbol")
