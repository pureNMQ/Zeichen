"""Migration coverage for the pending requirement state."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def _config(database_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


def _requirement_sql(database_path: Path) -> str:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'requirement'"
        ).fetchone()
    assert row is not None
    return row[0]


def test_pending_status_constraint_upgrades_and_downgrades(tmp_path, monkeypatch):
    database_path = tmp_path / "pending-status.db"
    config = _config(database_path, monkeypatch)

    # Test this migration's reversible boundary, not later irreversible releases.
    command.upgrade(config, "0813requirementpending")
    assert "'pending'" in _requirement_sql(database_path)

    command.downgrade(config, "0812memoryimprovejobs")
    assert "'pending'" not in _requirement_sql(database_path)
