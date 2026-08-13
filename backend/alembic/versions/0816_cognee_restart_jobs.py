"""Add durable Cognee restart job queue.

Revision ID: 0816cogneerestartjobs
Revises: 0815cogneeconfiguration
Create Date: 2026-08-12 19:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0816cogneerestartjobs"
down_revision = "0815cogneeconfiguration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cognee_restart_job",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed')", name="ck_cognee_restart_job_status"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cognee_restart_job_team_id", "cognee_restart_job", ["team_id"])
    op.create_index("ix_cognee_restart_job_status", "cognee_restart_job", ["status"])
    op.create_index(
        "uq_cognee_restart_job_active_team",
        "cognee_restart_job",
        ["team_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_cognee_restart_job_active_team", table_name="cognee_restart_job")
    op.drop_index("ix_cognee_restart_job_status", table_name="cognee_restart_job")
    op.drop_index("ix_cognee_restart_job_team_id", table_name="cognee_restart_job")
    op.drop_table("cognee_restart_job")
