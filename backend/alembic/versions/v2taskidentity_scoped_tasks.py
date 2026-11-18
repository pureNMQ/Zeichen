"""Give tasks stable requirement-local codes and retire task blocker edges."""

import re
from collections import defaultdict
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision = "v2taskidentity"
down_revision = "v2projectdesc"
branch_labels = None
depends_on = None

# Only rewrite resolved, project-qualified Markdown destinations. Prose, inline
# code, example URLs, external hosts and unresolved references retain their text.
_LINK = re.compile(
    r"(?P<open>\]\(<?)/projects/(?P<project>[0-9a-f-]{36})/"
    r"(?:tasks/(?P<direct>TASK-[1-9]\d*)|requirements/REQ-[1-9]\d*\?task=(?P<query>TASK-[1-9]\d*))"
    r"(?=[#> )])"
)


def _rewrite(body, mapping):
    def replace(match):
        project = match["project"]
        new = mapping.get((project, match["direct"] or match["query"]))
        if not new:
            return match[0]
        path = "tasks/" + new if match["direct"] else "requirements/" + new.split("-T")[0] + "?task=" + new
        return match["open"] + "/projects/" + project + "/" + path

    lines = []
    fence = None
    for line in body.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
        elif marker:
            fence = marker[1]
        elif "`" not in line and not line.startswith(("    ", "\t")):
            line = _LINK.sub(replace, line)
        lines.append(line)
    return "".join(lines)


def upgrade():
    db = op.get_bind()
    if db.dialect.name == "sqlite" and "code" not in {c["name"] for c in sa.inspect(db).get_columns("task")}:
        # 0914 never converted the old UUID SQLite fixture schema to short codes.
        return
    # PostgreSQL enforces VARCHAR widths. SQLite's TEXT affinity accepts the
    # new width without rebuilding heavily referenced tables.
    if db.dialect.name == "postgresql":
        op.alter_column("task", "code", type_=sa.String(36), existing_type=sa.String(16))
        op.alter_column("v2_timeline_entry", "source_task_code", type_=sa.String(36), existing_type=sa.String(16))
    op.add_column("task", sa.Column("legacy_code", sa.String(16)))
    op.create_index("uq_task_legacy_code", "task", ["project_id", "legacy_code"], unique=True)
    with op.batch_alter_table("entity_watch") as batch:
        batch.drop_constraint("uq_entity_watch_user_target", type_="unique")
        batch.create_unique_constraint("uq_entity_watch_user_target", ["project_id", "user_id", "target_type", "target_id"])
    # Retain the old graph for inspection; it cannot faithfully describe
    # requirement-level blockers. The archive has no active model or writer.
    op.execute("CREATE TABLE legacy_task_blocker_archive AS SELECT * FROM task_blocker")
    op.drop_table("task_blocker")

    meta = sa.MetaData()
    tasks = sa.Table("task", meta, autoload_with=db)
    counter = sa.Table("short_code_counter", meta, autoload_with=db)
    rows = db.execute(sa.select(tasks)).mappings().all()
    sequences = defaultdict(int)
    mapping = {}
    # Legacy order is numeric and deterministic, including soft-deleted tasks.
    for old in sorted(rows, key=lambda r: int(r["code"].split("-")[1])):
        project, req, old_code = old["project_id"], old["requirement_id"], old["code"]
        sequences[project, req] += 1
        code = f"{req}-T{sequences[project, req]}"
        mapping[str(UUID(str(project))), old_code] = code
        db.execute(tasks.insert().values({**dict(old), "code": code, "legacy_code": old_code}))
        params = {"project": project, "old": old_code, "code": code}
        db.execute(sa.text("UPDATE v2_timeline_entry SET source_task_code=:code "
                           "WHERE project_id=:project AND source_task_code=:old"), params)
        columns = [(table, "target_type", "target_id", "task") for table in
                   ("activity", "comment", "attachment", "notification", "entity_watch")]
        columns.extend([("reference", "from_type", "from_id", "task"), ("reference", "to_type", "to_id", "task"),
                        ("v2_wiki_reference", "target_kind", "target_id", "tasks"),
                        ("v2_file_association", "target_kind", "target_id", "tasks")])
        for table, kind_col, id_col, kind in columns:
            db.execute(sa.text(f'UPDATE "{table}" SET {id_col}=:code WHERE project_id=:project '
                               f'AND {kind_col}=:kind AND {id_col}=:old'), {**params, "kind": kind})
        db.execute(tasks.delete().where(tasks.c.project_id == project, tasks.c.code == old_code))
    for (project, req), last in sequences.items():
        db.execute(counter.insert().values(project_id=project, entity_type=req, last_seq=last))

    for table_name in ("v2_wiki", "v2_wiki_version", "v2_timeline_revision"):
        table = sa.Table(table_name, meta, autoload_with=db)
        pk = list(table.primary_key.columns)
        for row in db.execute(sa.select(*pk, table.c.body).where(table.c.body.like("%TASK-%"))).mappings():
            body = _rewrite(row["body"], mapping)
            if body != row["body"]:
                db.execute(table.update().where(*(c == row[c.name] for c in pk)).values(body=body))


def downgrade():
    raise RuntimeError("Task codes and retired dependency edges require restoring a pre-migration backup.")
