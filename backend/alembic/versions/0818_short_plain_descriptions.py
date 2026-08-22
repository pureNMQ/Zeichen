"""Limit requirement and task descriptions to single-line plain text."""

from alembic import op
import sqlalchemy as sa


revision = "0818shortdescriptions"
down_revision = "0817repositories"
branch_labels = None
depends_on = None


def _clean_existing(table: str) -> None:
    # Preserve existing records while making them conform to the new contract.
    newline = "char" if op.get_bind().dialect.name == "sqlite" else "chr"
    op.execute(
        sa.text(
            f"UPDATE {table} SET description = substr(trim(replace(replace(description, {newline}(13), ' '), {newline}(10), ' ')), 1, 512) "
            "WHERE description IS NOT NULL"
        )
    )


def _alter(table: str, constraint: str, downgrade: bool = False) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch_op:
            if not downgrade:
                batch_op.alter_column("description", existing_type=sa.Text(), type_=sa.String(512))
                batch_op.create_check_constraint(constraint, "description IS NULL OR length(description) <= 512")
            else:
                batch_op.drop_constraint(constraint, type_="check")
                batch_op.alter_column("description", existing_type=sa.String(512), type_=sa.Text())
    else:
        if downgrade:
            op.drop_constraint(constraint, table, type_="check")
            op.alter_column(table, "description", existing_type=sa.String(512), type_=sa.Text())
        else:
            op.alter_column(table, "description", existing_type=sa.Text(), type_=sa.String(512))
            op.create_check_constraint(constraint, table, "description IS NULL OR length(description) <= 512")


def upgrade() -> None:
    _clean_existing("requirement")
    _clean_existing("task")
    _alter("requirement", "ck_requirement_description_length")
    _alter("task", "ck_task_description_length")


def downgrade() -> None:
    _alter("task", "ck_task_description_length", downgrade=True)
    _alter("requirement", "ck_requirement_description_length", downgrade=True)
