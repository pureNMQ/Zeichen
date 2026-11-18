"""Add an optional plain-text project description to existing projects."""

from alembic import op
import sqlalchemy as sa

revision = "v2projectdesc"
down_revision = "v2timelinefiles"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("project", sa.Column("description", sa.String(1000), nullable=False, server_default=""))


def downgrade():
    op.drop_column("project", "description")
