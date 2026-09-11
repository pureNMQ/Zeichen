"""通知偏好与实体级关注(REQ 023b607e)。

Revision ID: 0912notifprefs
Revises: 0911taskblockers
Create Date: 2026-09-12 03:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0912notifprefs"
down_revision = "0911taskblockers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_preference",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scope_type", "scope_key", name="uq_notif_pref_user_scope"),
    )
    op.create_index("ix_notification_preference_user_id", "notification_preference", ["user_id"])
    op.create_table(
        "entity_watch",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "target_type", "target_id", name="uq_entity_watch_user_target"),
    )
    op.create_index("ix_entity_watch_user_id", "entity_watch", ["user_id"])
    op.create_index("ix_entity_watch_project_id", "entity_watch", ["project_id"])
    op.create_index("ix_entity_watch_target_type", "entity_watch", ["target_type"])
    op.create_index("ix_entity_watch_target_id", "entity_watch", ["target_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_watch_target_id", table_name="entity_watch")
    op.drop_index("ix_entity_watch_target_type", table_name="entity_watch")
    op.drop_index("ix_entity_watch_project_id", table_name="entity_watch")
    op.drop_index("ix_entity_watch_user_id", table_name="entity_watch")
    op.drop_table("entity_watch")
    op.drop_index("ix_notification_preference_user_id", table_name="notification_preference")
    op.drop_table("notification_preference")
