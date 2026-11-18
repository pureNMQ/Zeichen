"""Allow notifications for mentions in requirement and task bodies."""
from alembic import op
import sqlalchemy as sa

revision = "v2workmentions"
down_revision = "v2markdownrefs"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("v2_notification") as table:
        table.drop_constraint("ck_v2_notification_source", type_="check")
        table.alter_column("source_kind", existing_type=sa.String(8), type_=sa.String(16), existing_nullable=False)
        table.alter_column("source_code", existing_type=sa.String(16), type_=sa.String(36), existing_nullable=False)
        table.create_check_constraint("ck_v2_notification_source",
            "(source_kind = 'timeline' AND entry_id IS NOT NULL) OR "
            "(source_kind IN ('wiki', 'requirement', 'task') AND entry_id IS NULL)")


def downgrade():
    if op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM v2_notification WHERE source_kind IN ('requirement', 'task')"
    )):
        raise RuntimeError("Restore a backup to downgrade a database with work-body notifications")
    with op.batch_alter_table("v2_notification") as table:
        table.drop_constraint("ck_v2_notification_source", type_="check")
        table.alter_column("source_kind", existing_type=sa.String(16), type_=sa.String(8), existing_nullable=False)
        table.alter_column("source_code", existing_type=sa.String(36), type_=sa.String(16), existing_nullable=False)
        table.create_check_constraint("ck_v2_notification_source",
            "(source_kind = 'timeline' AND entry_id IS NOT NULL) OR (source_kind = 'wiki' AND entry_id IS NULL)")
