"""Add in-app notifications.

Revision ID: 0813notifications
Revises: 0812memoryimprovejobs
Create Date: 2026-08-09 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0813notifications"
down_revision = "0812memoryimprovejobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_user_id", "notification", ["user_id"])
    op.create_index("ix_notification_actor_id", "notification", ["actor_id"])
    op.create_index("ix_notification_read_at", "notification", ["read_at"])
    op.create_index(
        "ix_notification_user_read",
        "notification",
        ["user_id", "read_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_user_read", table_name="notification")
    op.drop_index("ix_notification_read_at", table_name="notification")
    op.drop_index("ix_notification_actor_id", table_name="notification")
    op.drop_index("ix_notification_user_id", table_name="notification")
    op.drop_table("notification")
