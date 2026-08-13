"""Migration coverage for repository records and their polymorphic target."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_repository_migration_creates_sqlite_table_and_target_constraints(tmp_path, monkeypatch):
    database_path = tmp_path / "repositories.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    columns = {row[1]: row for row in connection.execute("PRAGMA table_info(repository)")}
    assert {"name", "vcs_type", "other_vcs_type", "url", "normalized_url", "description", "default_branch"} <= set(columns)
    activity_sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activity'").fetchone()[0]
    assert "'repository'" in activity_sql
    connection.close()
