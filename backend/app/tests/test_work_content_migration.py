from importlib import util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_version_backfill_preserves_body_and_indexes_only_resolved_legacy_edges():
    migration = Path(__file__).parents[2] / "alembic/versions/v2workcontent_versioned_work_markdown.py"
    spec = util.spec_from_file_location("work_content_migration", migration)
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    pid = uuid4()
    original = "原始说明，保持原有换行。\n第二行"
    with create_engine("sqlite://").begin() as conn:
        conn.exec_driver_sql("CREATE TABLE user (id CHAR(32) PRIMARY KEY)")
        for table in ("requirement", "task"):
            extra = "requirement_id TEXT NOT NULL," if table == "task" else ""
            conn.exec_driver_sql(f"CREATE TABLE {table} (project_id CHAR(32), code TEXT, title TEXT,"
                f"description VARCHAR(512), updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, {extra}"
                f"PRIMARY KEY(project_id,code), CONSTRAINT ck_{table}_description_length "
                "CHECK(description IS NULL OR length(description)<=512))")
        conn.exec_driver_sql("CREATE TABLE v2_wiki (project_id CHAR(32), code TEXT, PRIMARY KEY(project_id,code))")
        conn.exec_driver_sql("CREATE TABLE reference (project_id CHAR(32), from_type TEXT, from_id TEXT, "
                             "to_type TEXT, to_id TEXT, deleted_at DATETIME)")
        conn.execute(text("INSERT INTO requirement (project_id,code,title,description) VALUES (:pid,'REQ-4','需求',:body)"),
                     {"pid": pid.hex, "body": original})
        conn.execute(text("INSERT INTO task (project_id,code,title,description,requirement_id) "
                          "VALUES (:pid,'REQ-4-T1','任务','', 'REQ-4')"), {"pid": pid.hex})
        for dest in ("REQ-4-T1", "REQ-4-T9"):
            conn.execute(text("INSERT INTO reference VALUES (:pid,'requirement','REQ-4','task',:dest,NULL)"),
                         {"pid": pid.hex, "dest": dest})
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        expected = f"{original}\n\n## 相关引用\n\n- [REQ-4-T1](/projects/{pid}/tasks/REQ-4-T1)"
        assert conn.scalar(text("SELECT description FROM requirement")) == expected
        assert conn.scalar(text("SELECT description FROM v2_work_version WHERE code='REQ-4'")) == expected
        assert conn.execute(text("SELECT target_kind,target_id FROM v2_work_reference")).all() == [("tasks", "REQ-4-T1")]
        assert conn.scalar(text("SELECT count(*) FROM v2_work_version")) == 2
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
