"""Add the pending requirement status and make it the creation default.

Revision ID: 0813requirementpending
Revises: 0812memoryimprovejobs
Create Date: 2026-08-12 10:00:00.000000
"""

from alembic import op


revision = "0813requirementpending"
down_revision = "0812memoryimprovejobs"
branch_labels = None
depends_on = None

FIVE_STATES = "'pending', 'backlog', 'in_progress', 'done', 'cancelled'"
FOUR_STATES = "'backlog', 'in_progress', 'done', 'cancelled'"


def _replace_status_constraint(states: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.drop_constraint("ck_requirement_status", type_="check")
            batch_op.create_check_constraint(
                "ck_requirement_status", f"status IN ({states})"
            )
    else:
        op.drop_constraint("ck_requirement_status", "requirement", type_="check")
        op.create_check_constraint(
            "ck_requirement_status", "requirement", f"status IN ({states})"
        )


def upgrade() -> None:
    _replace_status_constraint(FIVE_STATES)


def downgrade() -> None:
    op.execute("UPDATE requirement SET status = 'backlog' WHERE status = 'pending'")
    _replace_status_constraint(FOUR_STATES)
