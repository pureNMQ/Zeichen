"""Add project code repository records.

Revision ID: 0817repositories
Revises: 0816cogneerestartjobs
Create Date: 2026-08-13 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0817repositories"
down_revision = "0816cogneerestartjobs"
branch_labels = None
depends_on = None


def _target_values(include_repository: bool) -> str:
    values = ["requirement", "task", "document"]
    if include_repository:
        values.append("repository")
    values.extend(["project", "user"])
    return "(" + ", ".join(repr(value) for value in values) + ")"


def _replace_target_constraints(include_repository: bool) -> None:
    values = _target_values(include_repository)
    with op.batch_alter_table("comment") as batch_op:
        batch_op.drop_constraint("ck_comment_target_type", type_="check")
        batch_op.create_check_constraint("ck_comment_target_type", f"target_type IN {values}")
    with op.batch_alter_table("activity") as batch_op:
        batch_op.drop_constraint("ck_activity_target_type", type_="check")
        batch_op.create_check_constraint("ck_activity_target_type", f"target_type IN {values}")
    with op.batch_alter_table("attachment") as batch_op:
        batch_op.drop_constraint("ck_attachment_target_type", type_="check")
        batch_op.create_check_constraint("ck_attachment_target_type", f"target_type IN {values}")
    with op.batch_alter_table("reference") as batch_op:
        batch_op.drop_constraint("ck_reference_from_type", type_="check")
        batch_op.drop_constraint("ck_reference_to_type", type_="check")
        batch_op.create_check_constraint("ck_reference_from_type", f"from_type IN {values}")
        batch_op.create_check_constraint("ck_reference_to_type", f"to_type IN {values}")


def upgrade() -> None:
    op.create_table(
        "repository",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("vcs_type", sa.String(length=16), nullable=False),
        sa.Column("other_vcs_type", sa.String(length=64), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("default_branch", sa.String(length=256), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("vcs_type IN ('git', 'svn', 'other')", name="ck_repository_vcs_type"),
        sa.CheckConstraint("(vcs_type = 'other' AND other_vcs_type IS NOT NULL) OR (vcs_type IN ('git', 'svn') AND other_vcs_type IS NULL)", name="ck_repository_other_vcs_type"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repository_project_id", "repository", ["project_id"])
    _replace_target_constraints(True)


def downgrade() -> None:
    _replace_target_constraints(False)
    op.drop_index("ix_repository_project_id", table_name="repository")
    op.drop_table("repository")
