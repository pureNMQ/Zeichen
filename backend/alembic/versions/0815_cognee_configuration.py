"""Add workspace-managed Cognee configuration.

Revision ID: 0815cogneeconfiguration
Revises: 0814usernicknameavatar
Create Date: 2026-08-12 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0815cogneeconfiguration"
down_revision = "0814usernicknameavatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cognee_configuration",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("llm_provider", sa.String(length=64), nullable=False),
        sa.Column("llm_model", sa.String(length=256), nullable=False),
        sa.Column("llm_endpoint", sa.String(length=2048), nullable=True),
        sa.Column("llm_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("embedding_provider", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=256), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
        sa.Column("pending_restart", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id"),
    )
    op.create_index("ix_cognee_configuration_team_id", "cognee_configuration", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_cognee_configuration_team_id", table_name="cognee_configuration")
    op.drop_table("cognee_configuration")
