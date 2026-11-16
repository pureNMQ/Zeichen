"""Preserve the actor of workspace project deletions."""

import sqlalchemy as sa
from alembic import op

revision = "v2projecttrash"
down_revision = "v2keyonce"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("deleted_by", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_project_trash_actor", "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_constraint("fk_project_trash_actor", type_="foreignkey")
        batch.drop_column("deleted_by")
