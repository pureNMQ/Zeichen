"""Store explicit mentions, replies and shared acknowledgements."""

import sqlalchemy as sa
from alembic import op

revision = "v2notify"
down_revision = "v2wiki"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_notification",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("visibility", sa.String(12), nullable=False),
        sa.Column("source_kind", sa.String(8), nullable=False),
        sa.Column("source_key", sa.String(36), nullable=False),
        sa.Column("source_code", sa.String(16), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Uuid()),
        sa.Column("mentioned_user_ids", sa.JSON(), nullable=False),
        sa.Column("reply_user_id", sa.Uuid(), sa.ForeignKey("user.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("read_by_id", sa.Uuid(), sa.ForeignKey("user.id")),
        sa.UniqueConstraint(
            "project_id", "source_kind", "source_key", "source_version", "owner_id",
            name="uq_v2_notification_source_owner",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_code", "entry_id"],
            ["v2_timeline_entry.project_id", "v2_timeline_entry.requirement_code", "v2_timeline_entry.id"],
        ),
        sa.CheckConstraint("visibility IN ('shared', 'owner_only')", name="ck_v2_notification_visibility"),
        sa.CheckConstraint("source_version > 0", name="ck_v2_notification_version"),
        sa.CheckConstraint("(read_at IS NULL) = (read_by_id IS NULL)", name="ck_v2_notification_read"),
        sa.CheckConstraint(
            "(source_kind = 'timeline' AND entry_id IS NOT NULL) OR "
            "(source_kind = 'wiki' AND entry_id IS NULL)", name="ck_v2_notification_source",
        ),
    )
    op.create_index("ix_v2_notification_inbox", "v2_notification", ["owner_id", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_v2_notification_inbox", table_name="v2_notification")
    op.drop_table("v2_notification")
