"""Add the v2 mutation receipt table.

Revision ID: v2base
Revises: 1007wikimerge
"""

import sqlalchemy as sa
from alembic import op

revision = "v2base"
down_revision = "1007wikimerge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_command_receipt",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id"), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("operation", sa.String(64), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("v2_command_receipt")
