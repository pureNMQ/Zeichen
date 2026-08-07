"""Add the opaque project-to-cognee dataset mapping.

Revision ID: 0810memorydataset
Revises: 0808sqlitecoderef
Create Date: 2026-08-06 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0810memorydataset"
down_revision = "0808sqlitecoderef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_memory_grant_viewer_agent_id", table_name="memory_grant")
    op.drop_index("ix_memory_grant_target_agent_id", table_name="memory_grant")
    op.drop_index("ix_memory_grant_grantor_id", table_name="memory_grant")
    op.drop_table("memory_grant")
    op.create_table(
        "memory_dataset",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("cognee_dataset_id", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_memory_dataset_project"),
        sa.UniqueConstraint("cognee_dataset_id"),
    )
    op.create_index("ix_memory_dataset_project_id", "memory_dataset", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_dataset_project_id", table_name="memory_dataset")
    op.drop_table("memory_dataset")
    op.create_table(
        "memory_grant",
        sa.Column("grantor_id", sa.Uuid(), nullable=False),
        sa.Column("viewer_agent_id", sa.Uuid(), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("viewer_agent_id <> target_agent_id", name="ck_memory_grant_not_self"),
        sa.ForeignKeyConstraint(["grantor_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["viewer_agent_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_agent_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grantor_id", "viewer_agent_id", "target_agent_id", name="uq_memory_grant_grantor_viewer_target"),
    )
    op.create_index("ix_memory_grant_grantor_id", "memory_grant", ["grantor_id"])
    op.create_index("ix_memory_grant_target_agent_id", "memory_grant", ["target_agent_id"])
    op.create_index("ix_memory_grant_viewer_agent_id", "memory_grant", ["viewer_agent_id"])
