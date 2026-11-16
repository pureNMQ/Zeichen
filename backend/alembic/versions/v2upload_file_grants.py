"""Add short-lived raw-byte upload grants for MCP clients.

Revision ID: v2upload
Revises: v2files
"""

import sqlalchemy as sa
from alembic import op

revision = "v2upload"
down_revision = "v2files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_file_upload_grant",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_key.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("expected_size > 0", name="ck_v2_file_upload_size_positive"),
    )
    op.create_index("ix_v2_file_upload_grant_expiry", "v2_file_upload_grant", ["expires_at"])


def downgrade() -> None:
    op.drop_table("v2_file_upload_grant")
