"""Track session generations across account deactivation and reactivation."""

import sqlalchemy as sa
from alembic import op

revision = "v2members"
down_revision = "v2upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("session_epoch", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("user", "session_epoch")
