"""Index file links in all retained timeline revisions."""

import sqlalchemy as sa
from alembic import op

from app.v2.timeline_file_refs import file_reference_rows

revision = "v2timelinefiles"
down_revision = "v2worktrash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("The timeline file reference backfill requires an online Alembic upgrade")
    reference = op.create_table(
        "v2_timeline_file_reference",
        sa.Column("entry_id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Uuid(), primary_key=True),
        sa.ForeignKeyConstraint(["entry_id", "version"],
                                ["v2_timeline_revision.entry_id", "v2_timeline_revision.version"], ondelete="CASCADE"),
    )
    source = sa.table(
        "v2_timeline_revision", sa.column("entry_id", sa.Uuid()), sa.column("version", sa.Integer()),
        sa.column("project_id", sa.Uuid()), sa.column("body", sa.Text()),
    )
    bind = op.get_bind()
    statement = sa.select(source).where(source.c.body.is_not(None)).order_by(source.c.entry_id, source.c.version).limit(250)
    page = bind.execute(statement).all()
    while page:
        rows = [ref for item in page for ref in file_reference_rows(*item)]
        if rows:
            bind.execute(sa.insert(reference), rows)
        last = page[-1]
        page = bind.execute(statement.where(sa.tuple_(source.c.entry_id, source.c.version) >
                                           sa.tuple_(last.entry_id, last.version))).all()
    op.create_index("ix_v2_timeline_file_reference_file", reference.name, ["file_id", "entry_id", "version"])


def downgrade() -> None:
    op.drop_table("v2_timeline_file_reference")
