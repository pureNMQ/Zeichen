"""Create the independent code API reference aggregate.

Revision ID: 0807coderef
Revises: 0420docworkbench
Create Date: 2026-08-05 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0807coderef"
down_revision = "0420docworkbench"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_library",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("package", sa.String(length=256), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_library_project_id", "code_library", ["project_id"])
    op.create_table(
        "code_symbol",
        sa.Column("library_id", sa.Uuid(), nullable=False),
        sa.Column("owner_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("namespace", sa.String(length=256), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=False),
        sa.Column("accessibility", sa.String(length=32), nullable=False),
        sa.Column("source_declaration", sa.Text(), nullable=True),
        sa.Column("since_version", sa.String(length=64), nullable=True),
        sa.Column("deprecated", sa.Boolean(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("kind IN ('class', 'struct', 'interface', 'enum', 'function', 'constructor', 'method', 'field', 'property', 'constant')", name="ck_code_symbol_kind"),
        sa.ForeignKeyConstraint(["library_id"], ["code_library.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_symbol_id"], ["code_symbol.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_symbol_library_id", "code_symbol", ["library_id"])
    op.create_index("ix_code_symbol_owner_symbol_id", "code_symbol", ["owner_symbol_id"])
    op.create_table(
        "code_enum_member",
        sa.Column("enum_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("assigned_value", sa.String(length=256), nullable=True),
        sa.Column("summary", sa.String(length=512), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["enum_id"], ["code_symbol.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("enum_id", "position", name="uq_code_enum_member_position"),
        sa.UniqueConstraint("enum_id", "name", name="uq_code_enum_member_name"),
    )
    op.create_index("ix_code_enum_member_enum_id", "code_enum_member", ["enum_id"])
    op.create_table(
        "code_symbol_version",
        sa.Column("symbol_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["symbol_id"], ["code_symbol.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol_id", "revision", name="uq_code_symbol_version_revision"),
    )
    op.create_index("ix_code_symbol_version_symbol_id", "code_symbol_version", ["symbol_id"])
    target_values = "('requirement', 'task', 'document', 'code_symbol', 'project', 'user')"
    with op.batch_alter_table("comment") as batch_op:
        batch_op.drop_constraint("ck_comment_target_type", type_="check")
        batch_op.create_check_constraint("ck_comment_target_type", f"target_type IN {target_values}")
    with op.batch_alter_table("activity") as batch_op:
        batch_op.drop_constraint("ck_activity_target_type", type_="check")
        batch_op.create_check_constraint("ck_activity_target_type", f"target_type IN {target_values}")
    with op.batch_alter_table("attachment") as batch_op:
        batch_op.drop_constraint("ck_attachment_target_type", type_="check")
        batch_op.create_check_constraint("ck_attachment_target_type", f"target_type IN {target_values}")
    with op.batch_alter_table("reference") as batch_op:
        batch_op.drop_constraint("ck_reference_from_type", type_="check")
        batch_op.drop_constraint("ck_reference_to_type", type_="check")
        batch_op.create_check_constraint("ck_reference_from_type", f"from_type IN {target_values}")
        batch_op.create_check_constraint("ck_reference_to_type", f"to_type IN {target_values}")


def downgrade() -> None:
    target_values = "('requirement', 'task', 'document', 'project', 'user')"
    with op.batch_alter_table("reference") as batch_op:
        batch_op.drop_constraint("ck_reference_from_type", type_="check")
        batch_op.drop_constraint("ck_reference_to_type", type_="check")
        batch_op.create_check_constraint("ck_reference_from_type", f"from_type IN {target_values}")
        batch_op.create_check_constraint("ck_reference_to_type", f"to_type IN {target_values}")
    with op.batch_alter_table("attachment") as batch_op:
        batch_op.drop_constraint("ck_attachment_target_type", type_="check")
        batch_op.create_check_constraint("ck_attachment_target_type", f"target_type IN {target_values}")
    with op.batch_alter_table("activity") as batch_op:
        batch_op.drop_constraint("ck_activity_target_type", type_="check")
        batch_op.create_check_constraint("ck_activity_target_type", f"target_type IN {target_values}")
    with op.batch_alter_table("comment") as batch_op:
        batch_op.drop_constraint("ck_comment_target_type", type_="check")
        batch_op.create_check_constraint("ck_comment_target_type", f"target_type IN {target_values}")
    op.drop_index("ix_code_symbol_version_symbol_id", table_name="code_symbol_version")
    op.drop_table("code_symbol_version")
    op.drop_index("ix_code_enum_member_enum_id", table_name="code_enum_member")
    op.drop_table("code_enum_member")
    op.drop_index("ix_code_symbol_owner_symbol_id", table_name="code_symbol")
    op.drop_index("ix_code_symbol_library_id", table_name="code_symbol")
    op.drop_table("code_symbol")
    op.drop_index("ix_code_library_project_id", table_name="code_library")
    op.drop_table("code_library")
