"""requirement status four states

Revision ID: 0910state4
Revises: fae8db738539
Create Date: 2026-08-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0910state4'
down_revision: Union[str, None] = 'fae8db738539'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FOUR_STATES = "'backlog', 'in_progress', 'done', 'cancelled'"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.drop_constraint("ck_requirement_status", type_="check")
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.create_check_constraint(
                "ck_requirement_status", f"status IN ({FOUR_STATES})"
            )
    else:
        op.drop_constraint("ck_requirement_status", "requirement", type_="check")
        op.create_check_constraint(
            "ck_requirement_status", "requirement", f"status IN ({FOUR_STATES})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.drop_constraint("ck_requirement_status", type_="check")
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.create_check_constraint(
                "ck_requirement_status",
                "status IN ('backlog', 'in_progress', 'verifying', 'done', 'cancelled')",
            )
    else:
        op.drop_constraint("ck_requirement_status", "requirement", type_="check")
        op.create_check_constraint(
            "ck_requirement_status",
            "requirement",
            "status IN ('backlog', 'in_progress', 'verifying', 'done', 'cancelled')",
        )
