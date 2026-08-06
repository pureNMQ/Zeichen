"""Make code-reference timestamp defaults valid on SQLite.

Revision ID: 0808sqlitecoderef
Revises: 0807coderef
Create Date: 2026-08-06 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0808sqlitecoderef"
down_revision = "0807coderef"
branch_labels = None
depends_on = None


def _set_sqlite_timestamp_defaults(default: str) -> None:
    for table_name in ("code_library", "code_symbol"):
        with op.batch_alter_table(table_name, recreate="always") as batch_op:
            for column_name in ("created_at", "updated_at"):
                batch_op.alter_column(
                    column_name,
                    existing_type=sa.DateTime(timezone=True),
                    existing_nullable=False,
                    server_default=sa.text(default),
                )


def upgrade() -> None:
    # ``now()`` in 0807coderef is valid on PostgreSQL but SQLite only supports
    # CURRENT_TIMESTAMP as a built-in timestamp default.
    if op.get_bind().dialect.name == "sqlite":
        _set_sqlite_timestamp_defaults("CURRENT_TIMESTAMP")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _set_sqlite_timestamp_defaults("now()")
