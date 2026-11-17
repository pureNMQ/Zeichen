"""Record actors for recoverable requirement and task removals."""

import sqlalchemy as sa
from alembic import op

revision = "v2worktrash"
down_revision = "v2members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("requirement", "task"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("deleted_by", sa.Uuid()))
            batch.create_foreign_key(f"fk_{table}_deleted_by", "user", ["deleted_by"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    for table in ("task", "requirement"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_deleted_by", type_="foreignkey")
            batch.drop_column("deleted_by")
