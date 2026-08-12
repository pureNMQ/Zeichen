"""Add user nickname/avatar and allow workspace-scoped avatar attachments.

Revision ID: 0814usernicknameavatar
Revises: 0813requirementpending
Create Date: 2026-08-12 10:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0814usernicknameavatar"
down_revision = "0813requirementpending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("nickname", sa.String(length=64), nullable=True))
    op.add_column("user", sa.Column("avatar", sa.Uuid(), nullable=True))
    with op.batch_alter_table("attachment") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM attachment WHERE target_type = 'user' AND project_id IS NULL")
    with op.batch_alter_table("attachment") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("user", "avatar")
    op.drop_column("user", "nickname")
