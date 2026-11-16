"""Add personal filter views (project_filter_view).

Revision ID: 0819filterviews
Revises: 0819shortdescmerge
Create Date: 2026-08-15 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0819filterviews"
down_revision = "0819shortdescmerge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_filter_view",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "user_id", "entity_type", "name",
            name="uq_project_filter_view_scope_name",
        ),
    )
    op.create_index("ix_project_filter_view_project_id", "project_filter_view", ["project_id"])
    op.create_index("ix_project_filter_view_user_id", "project_filter_view", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_project_filter_view_user_id", table_name="project_filter_view")
    op.drop_index("ix_project_filter_view_project_id", table_name="project_filter_view")
    op.drop_table("project_filter_view")
