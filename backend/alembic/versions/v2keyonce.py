"""Drop reversible API key material while preserving authentication digests."""

from alembic import op

revision = "v2keyonce"
down_revision = "v2base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("api_key", "token_encrypted")


def downgrade() -> None:
    raise RuntimeError("Reversible key material was deleted. Recover the pre-cutover database snapshot.")
