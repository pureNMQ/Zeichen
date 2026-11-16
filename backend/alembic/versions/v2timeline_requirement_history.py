"""Add project-scoped requirement timeline and immutable revisions.

Revision ID: v2timeline
Revises: v2base
"""

import sqlalchemy as sa
from alembic import op

revision = "v2timeline"
down_revision = "v2base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_timeline_entry",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_code", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("source_task_code", sa.String(16)),
        sa.Column("reply_to_id", sa.Uuid()),
        sa.Column("latest_version", sa.Integer()),
        sa.Column("event_type", sa.String(64)),
        sa.Column("event_data", sa.JSON(none_as_null=True)),
        sa.UniqueConstraint("project_id", "requirement_code", "id", name="uq_v2_timeline_entry_scope"),
        sa.ForeignKeyConstraint(
            ["project_id", "requirement_code"], ["requirement.project_id", "requirement.code"]
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_task_code"], ["task.project_id", "task.code"]
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "requirement_code", "reply_to_id"],
            ["v2_timeline_entry.project_id", "v2_timeline_entry.requirement_code", "v2_timeline_entry.id"],
        ),
        sa.CheckConstraint("reply_to_id IS NULL OR reply_to_id <> id", name="ck_v2_timeline_no_self_reply"),
        sa.CheckConstraint(
            "(kind = 'manual' AND latest_version IS NOT NULL AND latest_version > 0 AND event_type IS NULL) OR "
            "(kind = 'system' AND latest_version IS NULL AND event_type IS NOT NULL AND reply_to_id IS NULL)",
            name="ck_v2_timeline_entry_kind",
        ),
    )
    op.create_index(
        "ix_v2_timeline_entry_order", "v2_timeline_entry", ["project_id", "requirement_code", "occurred_at", "id"]
    )
    op.create_table(
        "v2_timeline_revision",
        sa.Column("entry_id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("requirement_code", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("reason", sa.String(512)),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "requirement_code", "entry_id"],
            ["v2_timeline_entry.project_id", "v2_timeline_entry.requirement_code", "v2_timeline_entry.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(version = 1 AND kind = 'create' AND body IS NOT NULL) OR "
            "(version > 1 AND ((kind = 'revise' AND body IS NOT NULL) OR "
            "(kind = 'withdraw' AND body IS NULL)))",
            name="ck_v2_timeline_revision_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("v2_timeline_revision")
    op.drop_index("ix_v2_timeline_entry_order", table_name="v2_timeline_entry")
    op.drop_table("v2_timeline_entry")
