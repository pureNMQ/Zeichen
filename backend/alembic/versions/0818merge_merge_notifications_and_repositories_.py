"""merge notifications and repositories heads

Revision ID: 0818merge
Revises: 0813notifications, 0817repositories
Create Date: 2026-08-14 01:11:28.008912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0818merge'
down_revision: Union[str, None] = ('0813notifications', '0817repositories')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
