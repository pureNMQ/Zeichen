"""Retire separately editable references after folding them into Markdown."""
import logging

from alembic import op
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.v2.import_legacy_references import migrate_references

revision = "v2markdownrefs"
down_revision = "v2reqboard"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not inspect(bind).has_table("v2_work_version"):
        return
    with Session(bind) as db:
        _, exceptions = migrate_references(db)
        db.commit()
    if exceptions:
        logging.getLogger("alembic.runtime.migration").warning(
            "%d unresolved references retained for the post-import report", len(exceptions))


def downgrade():
    raise RuntimeError("Restore the pre-migration backup to downgrade Markdown references")
