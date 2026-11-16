"""Add structured Wiki documents and immutable version references.

Revision ID: v2wiki
Revises: v2base
"""

import sqlalchemy as sa
from alembic import op

revision = "v2wiki"
down_revision = "v2timeline"
branch_labels = None
depends_on = None


def _fields() -> tuple[sa.Column, ...]:
    return (
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("category", sa.Text()),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "v2_wiki",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("project.id"), primary_key=True),
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("parent_id", sa.String(16)),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *_fields(),
        sa.ForeignKeyConstraint(["project_id", "parent_id"], ["v2_wiki.project_id", "v2_wiki.code"]),
        sa.CheckConstraint("version_no > 0", name="ck_v2_wiki_version_positive"),
    )
    op.create_index("ix_v2_wiki_parent", "v2_wiki", ["project_id", "parent_id"])
    op.create_table(
        "v2_wiki_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("wiki_code", sa.String(16), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        *_fields(),
        sa.ForeignKeyConstraint(
            ["project_id", "wiki_code"], ["v2_wiki.project_id", "v2_wiki.code"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("project_id", "wiki_code", "version_no", name="uq_v2_wiki_version"),
        sa.CheckConstraint("version_no > 0", name="ck_v2_wiki_snapshot_version_positive"),
    )
    op.create_table(
        "v2_wiki_reference",
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("wiki_code", sa.String(16), primary_key=True),
        sa.Column("version_no", sa.Integer(), primary_key=True),
        sa.Column("target_kind", sa.String(16), primary_key=True),
        sa.Column("target_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(
            ["project_id", "wiki_code", "version_no"],
            ["v2_wiki_version.project_id", "v2_wiki_version.wiki_code", "v2_wiki_version.version_no"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_v2_wiki_reference_target", "v2_wiki_reference", ["project_id", "target_kind", "target_id"])


def downgrade() -> None:
    op.drop_table("v2_wiki_reference")
    op.drop_table("v2_wiki_version")
    op.drop_table("v2_wiki")
