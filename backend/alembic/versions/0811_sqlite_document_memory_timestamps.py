"""Repair SQLite timestamp defaults for document directories and memory datasets.

Revision ID: 0811sqlitetimestamps
Revises: 0810memorydataset
Create Date: 2026-08-06 16:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0811sqlitetimestamps"
down_revision = "0810memorydataset"
branch_labels = None
depends_on = None


def _set_sqlite_timestamp_default(table_name: str, column_names: tuple[str, ...], default: str) -> None:
    with op.batch_alter_table(table_name, recreate="always") as batch_op:
        for column_name in column_names:
            batch_op.alter_column(
                column_name,
                existing_type=sa.DateTime(timezone=True),
                existing_nullable=False,
                server_default=sa.text(default),
            )


def upgrade() -> None:
    """SQLite has CURRENT_TIMESTAMP but does not implement PostgreSQL's now()."""
    if op.get_bind().dialect.name != "sqlite":
        return
    _set_sqlite_timestamp_default("document_directory", ("created_at", "updated_at"), "CURRENT_TIMESTAMP")
    _set_sqlite_timestamp_default("memory_dataset", ("created_at",), "CURRENT_TIMESTAMP")


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    _set_sqlite_timestamp_default("document_directory", ("created_at", "updated_at"), "now()")
    _set_sqlite_timestamp_default("memory_dataset", ("created_at",), "now()")
