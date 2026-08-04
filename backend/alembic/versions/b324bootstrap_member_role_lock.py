"""Protect the founding human workspace account.

Revision ID: b324bootstrap
Revises: 0910state4
Create Date: 2026-08-04 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b324bootstrap"
down_revision: Union[str, None] = "0910state4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("is_bootstrap", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Existing installations gain exactly one protected account: the earliest
    # active human user.  New accounts default to false in the model/database.
    op.execute(
        sa.text(
            'UPDATE "user" SET is_bootstrap = true '
            'WHERE id = (SELECT id FROM "user" '
            'WHERE deleted_at IS NULL AND is_agent = false '
            'ORDER BY created_at, id LIMIT 1)'
        )
    )
    op.alter_column("user", "is_bootstrap", server_default=None)


def downgrade() -> None:
    op.drop_column("user", "is_bootstrap")
