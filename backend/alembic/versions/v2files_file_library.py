"""Add the v2 project file library and temporary read grants.

Revision ID: v2files
Revises: v2base
"""

import sqlalchemy as sa
from alembic import op

revision = "v2files"
down_revision = "v2notify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "v2_project_file",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id"), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("deleted_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("size > 0", name="ck_v2_project_file_size_positive"),
    )
    op.create_index("ix_v2_project_file_created", "v2_project_file", ["project_id", "created_at", "id"])
    op.create_table(
        "v2_file_association",
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("file_id", sa.Uuid(), primary_key=True),
        sa.Column("target_kind", sa.String(16), primary_key=True),
        sa.Column("target_id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.ForeignKeyConstraint(
            ["project_id", "file_id"], ["v2_project_file.project_id", "v2_project_file.id"], ondelete="CASCADE",
        ),
        sa.CheckConstraint("target_kind IN ('project', 'requirements', 'tasks', 'wiki', 'timeline')",
                           name="ck_v2_file_association_target_kind"),
    )
    op.create_index("ix_v2_file_association_target", "v2_file_association", ["project_id", "target_kind", "target_id"])
    op.create_table(
        "v2_file_grant",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), sa.ForeignKey("api_key.id", ondelete="CASCADE")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inline", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "file_id"], ["v2_project_file.project_id", "v2_project_file.id"], ondelete="CASCADE",
        ),
    )
    op.create_index("ix_v2_file_grant_file", "v2_file_grant", ["project_id", "file_id"])
    op.create_index("ix_v2_file_grant_expiry", "v2_file_grant", ["expires_at"])


def downgrade() -> None:
    op.drop_table("v2_file_grant")
    op.drop_table("v2_file_association")
    op.drop_table("v2_project_file")
