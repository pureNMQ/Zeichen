"""Promote work descriptions to Markdown, retaining the current state as version one."""

from itertools import groupby
from uuid import UUID

from alembic import op
import sqlalchemy as sa

from app.v2.markdown_refs import extract_markdown_refs
from app.v2.resource_refs import ResourceKind, ResourceRef

revision = "v2workcontent"
down_revision = "v2taskidentity"
branch_labels = None
depends_on = None


def _include_legacy_links(bind):
    """Preserve identifiable links formerly entered in the separate create dialog."""
    meta = sa.MetaData()
    ref = sa.Table("reference", meta, autoload_with=bind)
    targets = {"document": ("v2_wiki", ResourceKind.WIKI), "task": ("task", ResourceKind.TASK),
               "requirement": ("requirement", ResourceKind.REQUIREMENT)}
    for source_kind in ("requirement", "task"):
        source = sa.Table(source_kind, meta, autoload_with=bind)
        selects = []
        for target_kind, (target_table, kind) in targets.items():
            target = sa.Table(target_table, meta, autoload_with=bind).alias()
            selects.append(sa.select(ref.c.project_id, ref.c.from_id, sa.literal(kind.value).label("kind"),
                                     ref.c.to_id).join(target, sa.and_(target.c.project_id == ref.c.project_id,
                                     target.c.code == ref.c.to_id)).where(ref.c.from_type == source_kind,
                                     ref.c.to_type == target_kind, ref.c.deleted_at.is_(None)))
        edges = sa.union(*selects).subquery()
        rows = bind.execute(sa.select(edges).order_by(edges.c.project_id, edges.c.from_id, edges.c.kind, edges.c.to_id))
        for (pid, code), group in groupby(rows, key=lambda row: (row.project_id, row.from_id)):
            key = sa.and_(source.c.project_id == pid, source.c.code == code)
            description = bind.scalar(sa.select(source.c.description).where(key)) or ""
            project = UUID(str(pid))
            existing = extract_markdown_refs(description, project)
            links = [ResourceRef(project, ResourceKind(row.kind), row.to_id) for row in group]
            additions = [f"- [{link.identifier}]({link.path})" for link in links if link not in existing]
            if additions:
                body = (description + "\n\n" if description else "") + "## 相关引用\n\n" + "\n".join(additions)
                bind.execute(source.update().where(key).values(description=body))


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and "code" not in {c["name"] for c in sa.inspect(bind).get_columns("task")}:
        # The historical SQLite chain skips migration 0914's project-scoped PK rebuild.
        return
    if bind.dialect.name == "sqlite" and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Use an isolated SQLite migration connection with foreign_keys=OFF for table rebuilds")
    for table in ("requirement", "task"):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_description_length", type_="check")
            if table == "task":
                batch.create_check_constraint("ck_task_code_parent", "code LIKE requirement_id || '-T_%'")
            batch.alter_column("description", existing_type=sa.String(512), type_=sa.Text())
            batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    history = op.create_table(
        "v2_work_version", sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(36), primary_key=True), sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("requirement_code", sa.String(16), nullable=False), sa.Column("task_code", sa.String(36)),
        sa.Column("title", sa.String(256), nullable=False), sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.ForeignKeyConstraint(["project_id", "requirement_code"], ["requirement.project_id", "requirement.code"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id", "task_code"], ["task.project_id", "task.code"], ondelete="CASCADE"),
        sa.CheckConstraint("version > 0 AND ((task_code IS NULL AND code = requirement_code) OR (task_code IS NOT NULL AND code = task_code))", name="ck_work_version_subject"),
    )
    refs = op.create_table(
        "v2_work_reference", sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(36), primary_key=True), sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("target_kind", sa.String(16), primary_key=True), sa.Column("target_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(["project_id", "code", "version"],
                                ["v2_work_version.project_id", "v2_work_version.code", "v2_work_version.version"], ondelete="CASCADE"),
    )
    op.create_index("ix_work_reference_target", refs.name, ["project_id", "target_kind", "target_id"])
    _include_legacy_links(bind)
    for table, parent, task in (("requirement", "code", "NULL"), ("task", "requirement_id", "code")):
        # Last editor is not reliably recoverable for pre-versioned records.
        bind.execute(sa.text(f"INSERT INTO v2_work_version "
                             "(project_id, code, version, requirement_code, task_code, title, description, created_at) "
                             f"SELECT project_id, code, 1, {parent}, {task}, title, description, updated_at FROM {table}"))
    rows = bind.execute(sa.select(history.c.project_id, history.c.code, history.c.description).where(
        history.c.description.is_not(None)))
    for batch in rows.partitions(250):
        links = [dict(project_id=r.project_id, code=r.code, version=1, target_kind=link.kind.value, target_id=link.identifier)
                 for r in batch for link in extract_markdown_refs(r.description, r.project_id)]
        if links:
            bind.execute(refs.insert(), links)


def downgrade():
    # Downgrading would discard document history or truncate Markdown bodies.
    raise RuntimeError("Restore a pre-migration backup to downgrade versioned work content")
