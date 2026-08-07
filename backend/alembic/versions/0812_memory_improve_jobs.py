"""Add durable asynchronous session-improve jobs.

Revision ID: 0812memoryimprovejobs
Revises: 0811sqlitetimestamps
Create Date: 2026-08-07 15:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0812memoryimprovejobs"
down_revision = "0811sqlitetimestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_improve_job",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'upstream_busy', 'timed_out', 'unknown')",
            name="ck_memory_improve_job_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_agent_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_improve_job_project_id", "memory_improve_job", ["project_id"])
    op.create_index("ix_memory_improve_job_target_agent_id", "memory_improve_job", ["target_agent_id"])
    op.create_index("ix_memory_improve_job_requested_by_id", "memory_improve_job", ["requested_by_id"])
    op.create_index("ix_memory_improve_job_status", "memory_improve_job", ["status"])
    op.create_index(
        "uq_memory_improve_job_active_session",
        "memory_improve_job",
        ["project_id", "target_agent_id", "session_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_memory_improve_job_active_session", table_name="memory_improve_job")
    op.drop_index("ix_memory_improve_job_status", table_name="memory_improve_job")
    op.drop_index("ix_memory_improve_job_requested_by_id", table_name="memory_improve_job")
    op.drop_index("ix_memory_improve_job_target_agent_id", table_name="memory_improve_job")
    op.drop_index("ix_memory_improve_job_project_id", table_name="memory_improve_job")
    op.drop_table("memory_improve_job")
