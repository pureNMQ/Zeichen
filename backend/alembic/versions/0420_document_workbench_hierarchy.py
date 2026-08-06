"""Add document hierarchy, directories and complete version snapshots.

Revision ID: 0420docworkbench
Revises: d515password_setup
Create Date: 2026-08-04 16:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0420docworkbench"
down_revision: Union[str, None] = "d515password_setup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_directory",
        sa.Column("module_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("module_type IN ('glossary')", name="ck_document_directory_module_type"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["document_directory.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_directory_project_id", "document_directory", ["project_id"])
    op.create_index("ix_document_directory_parent_id", "document_directory", ["parent_id"])

    with op.batch_alter_table("document") as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("directory_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key("fk_document_parent_id", "document", ["parent_id"], ["id"], ondelete="SET NULL")
        batch_op.create_foreign_key("fk_document_directory_id", "document_directory", ["directory_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_document_parent_id", ["parent_id"])
        batch_op.create_index("ix_document_directory_id", ["directory_id"])

    with op.batch_alter_table("document_version") as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=256), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("metadata", sa.JSON(), nullable=True))
        batch_op.alter_column("title", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("document_version") as batch_op:
        batch_op.drop_column("metadata")
        batch_op.drop_column("title")
    with op.batch_alter_table("document") as batch_op:
        batch_op.drop_index("ix_document_directory_id")
        batch_op.drop_index("ix_document_parent_id")
        batch_op.drop_constraint("fk_document_directory_id", type_="foreignkey")
        batch_op.drop_constraint("fk_document_parent_id", type_="foreignkey")
        batch_op.drop_column("directory_id")
        batch_op.drop_column("parent_id")
    op.drop_index("ix_document_directory_parent_id", table_name="document_directory")
    op.drop_index("ix_document_directory_project_id", table_name="document_directory")
    op.drop_table("document_directory")
