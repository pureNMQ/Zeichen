"""Merge short-description and notification/repository migration heads.

Revision ID: 0819shortdescmerge
Revises: 0818shortdescriptions, 0818merge
Create Date: 2026-08-14
"""

from collections.abc import Sequence


revision: str = "0819shortdescmerge"
down_revision: tuple[str, str] = ("0818shortdescriptions", "0818merge")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
