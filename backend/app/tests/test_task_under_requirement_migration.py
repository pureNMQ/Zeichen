"""Migration coverage for 任务收归需求(ADR 0003,rev 0913taskunderreq)。

- 已取消无归属任务软删;非取消态存活独立任务 → 迁移停下人工确认
- 任务评论硬删;verifying 任务置 done;CHECK 约束切换;requirement_id NOT NULL
"""

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def _config(database_path: Path, monkeypatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    return Config(str(Path(__file__).parents[2] / "alembic.ini"))


def _seed_pre_migration(database_path: Path, *, live_orphan: bool = False) -> dict:
    """在 0912notifprefs 版本上插入固定数据,返回各实体 uuid 文本。"""
    ids = {k: str(uuid.uuid4()) for k in ("team", "user", "project", "req", "t_verifying",
                                            "t_orphan_cancelled", "t_orphan_live", "t_kept",
                                            "c_task", "c_requirement")}
    with sqlite3.connect(database_path) as conn:
        conn.execute(
            "INSERT INTO team (id, name, created_at, updated_at) VALUES (?, 't', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (ids["team"],),
        )
        conn.execute(
            "INSERT INTO user (id, username, password_hash, is_agent, is_bootstrap, created_at, updated_at) "
            "VALUES (?, 'u', 'x', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (ids["user"],),
        )
        conn.execute(
            "INSERT INTO project (id, team_id, name, created_at, updated_at) VALUES (?, ?, 'p', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (ids["project"], ids["team"]),
        )
        conn.execute(
            "INSERT INTO requirement (id, project_id, title, status, created_at, updated_at) "
            "VALUES (?, ?, 'r', 'in_progress', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (ids["req"], ids["project"]),
        )

        def task(tid: str, status: str, requirement_id: str | None):
            conn.execute(
                "INSERT INTO task (id, project_id, title, status, requirement_id, created_at, updated_at) "
                "VALUES (?, ?, 't', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (tid, ids["project"], status, requirement_id),
            )

        task(ids["t_verifying"], "verifying", ids["req"])
        task(ids["t_kept"], "backlog", ids["req"])
        task(ids["t_orphan_cancelled"], "cancelled", None)
        # 此前已软删的无归属任务同样物理清理(NOT NULL 收紧要求)
        conn.execute(
            "INSERT INTO task (id, project_id, title, status, requirement_id, created_at, updated_at, deleted_at) "
            "VALUES (?, ?, 'old-orphan', 'cancelled', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (str(uuid.uuid4()), ids["project"]),
        )
        if live_orphan:
            task(ids["t_orphan_live"], "backlog", None)
        conn.execute(
            "INSERT INTO comment (id, project_id, target_type, target_id, author_id, body, created_at, updated_at) "
            "VALUES (?, ?, 'task', ?, ?, 'task comment', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (ids["c_task"], ids["project"], ids["t_kept"], ids["user"]),
        )
        conn.execute(
            "INSERT INTO comment (id, project_id, target_type, target_id, author_id, body, created_at, updated_at) "
            "VALUES (?, ?, 'requirement', ?, ?, 'req comment', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (ids["c_requirement"], ids["project"], ids["req"], ids["user"]),
        )
    return ids


def test_upgrade_migrates_data_and_constraints(tmp_path, monkeypatch):
    database_path = tmp_path / "under-req.db"
    config = _config(database_path, monkeypatch)
    command.upgrade(config, "0912notifprefs")
    ids = _seed_pre_migration(database_path)
    command.upgrade(config, "head")

    with sqlite3.connect(database_path) as conn:
        # 无归属任务物理删除;有归属任务不受影响
        orphan_rows = conn.execute(
            "SELECT COUNT(*) FROM task WHERE requirement_id IS NULL"
        ).fetchone()[0]
        assert orphan_rows == 0
        kept = conn.execute(
            "SELECT deleted_at IS NULL, requirement_id FROM task WHERE id = ?", (ids["t_kept"],)
        ).fetchone()
        assert kept == (1, ids["req"])

        # verifying 任务 → done
        status = conn.execute(
            "SELECT status FROM task WHERE id = ?", (ids["t_verifying"],)
        ).fetchone()[0]
        assert status == "done"

        # 任务评论硬删;需求评论保留
        task_comments = conn.execute("SELECT COUNT(*) FROM comment WHERE target_type = 'task'").fetchone()[0]
        assert task_comments == 0
        req_comments = conn.execute(
            "SELECT COUNT(*) FROM comment WHERE id = ?", (ids["c_requirement"],)
        ).fetchone()[0]
        assert req_comments == 1

        # requirement_id NOT NULL
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task (id, project_id, title, status, requirement_id, created_at, updated_at) "
                "VALUES (?, ?, 'orphan', 'backlog', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (str(uuid.uuid4()), ids["project"]),
            )

        # CHECK 约束:task 无 verifying;requirement 有 verifying
        task_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='task'"
        ).fetchone()[0]
        requirement_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='requirement'"
        ).fetchone()[0]
        assert "'verifying'" not in task_sql
        assert "'verifying'" in requirement_sql
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task (id, project_id, title, status, requirement_id, created_at, updated_at) "
                "VALUES (?, ?, 'v', 'verifying', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (str(uuid.uuid4()), ids["project"], ids["req"]),
            )
        conn.execute(
            "INSERT INTO requirement (id, project_id, title, status, created_at, updated_at) "
            "VALUES (?, ?, 'v', 'verifying', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (str(uuid.uuid4()), ids["project"]),
        )


def test_upgrade_stops_on_live_orphan(tmp_path, monkeypatch):
    """非取消态存活独立任务 → 迁移停下(RuntimeError),数据库停留在 0912。"""
    database_path = tmp_path / "live-orphan.db"
    config = _config(database_path, monkeypatch)
    command.upgrade(config, "0912notifprefs")
    ids = _seed_pre_migration(database_path, live_orphan=True)

    with pytest.raises(RuntimeError, match="人工确认"):
        command.upgrade(config, "head")

    with sqlite3.connect(database_path) as conn:
        live = conn.execute(
            "SELECT deleted_at IS NULL FROM task WHERE id = ?", (ids["t_orphan_live"],)
        ).fetchone()[0]
        assert live == 1
        comments = conn.execute("SELECT COUNT(*) FROM comment WHERE target_type = 'task'").fetchone()[0]
        assert comments == 1
