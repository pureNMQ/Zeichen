"""Migration coverage for bounded, single-line requirement/task descriptions."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def _config(database_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


def test_short_description_migration_normalizes_existing_data(tmp_path, monkeypatch):
    database_path = tmp_path / "short-descriptions.db"
    config = _config(database_path, monkeypatch)
    command.upgrade(config, "0817repositories")

    with sqlite3.connect(database_path) as connection:
        connection.execute("INSERT INTO team (id, name) VALUES ('00000000000000000000000000000001', 'team')")
        connection.execute("INSERT INTO project (id, team_id, name) VALUES ('00000000000000000000000000000002', '00000000000000000000000000000001', 'project')")
        connection.execute("INSERT INTO requirement (id, project_id, title, description, status) VALUES ('00000000000000000000000000000003', '00000000000000000000000000000002', 'requirement', ?, 'pending')", ("a" * 510 + "\r\nlong",))
        connection.execute("INSERT INTO task (id, project_id, title, description, status) VALUES ('00000000000000000000000000000004', '00000000000000000000000000000002', 'task', ?, 'backlog')", ("first\nsecond",))
        connection.commit()

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        requirement_description = connection.execute("SELECT description FROM requirement").fetchone()[0]
        task_description = connection.execute("SELECT description FROM task").fetchone()[0]
        assert len(requirement_description) == 512
        assert "\n" not in requirement_description and "\r" not in requirement_description
        assert task_description == "first second"

    command.downgrade(config, "0817repositories")
