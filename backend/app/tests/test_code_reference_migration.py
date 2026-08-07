"""SQLite compatibility checks for the independent code-reference migrations."""

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_sqlite_code_library_timestamps_accept_inserts_after_upgrade(tmp_path, monkeypatch):
    """Existing SQLite databases must not retain PostgreSQL's ``now()`` default."""
    database_path = tmp_path / "code-reference.db"
    connection = sqlite3.connect(database_path)
    connection.executescript("""
        CREATE TABLE "user" (id CHAR(32) PRIMARY KEY);
        CREATE TABLE project (id CHAR(32) PRIMARY KEY);
        CREATE TABLE code_library (
            name VARCHAR(128) NOT NULL,
            language VARCHAR(32) NOT NULL,
            package VARCHAR(256) NOT NULL,
            version VARCHAR(64),
            id CHAR(32) PRIMARY KEY,
            created_at DATETIME DEFAULT (now()) NOT NULL,
            updated_at DATETIME DEFAULT (now()) NOT NULL,
            deleted_at DATETIME,
            created_by CHAR(32),
            project_id CHAR(32) NOT NULL,
            FOREIGN KEY(created_by) REFERENCES "user" (id),
            FOREIGN KEY(project_id) REFERENCES project (id)
        );
        CREATE TABLE code_symbol (
            library_id CHAR(32) NOT NULL,
            owner_symbol_id CHAR(32),
            namespace VARCHAR(256),
            kind VARCHAR(32) NOT NULL,
            name VARCHAR(256) NOT NULL,
            summary VARCHAR(512) NOT NULL,
            remarks TEXT NOT NULL,
            accessibility VARCHAR(32) NOT NULL,
            source_declaration TEXT,
            since_version VARCHAR(64),
            deprecated BOOLEAN NOT NULL,
            definition JSON NOT NULL,
            revision INTEGER NOT NULL,
            id CHAR(32) PRIMARY KEY,
            created_at DATETIME DEFAULT (now()) NOT NULL,
            updated_at DATETIME DEFAULT (now()) NOT NULL,
            deleted_at DATETIME,
            created_by CHAR(32),
            FOREIGN KEY(library_id) REFERENCES code_library (id),
            FOREIGN KEY(owner_symbol_id) REFERENCES code_symbol (id),
            FOREIGN KEY(created_by) REFERENCES "user" (id)
        );
        CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL);
        INSERT INTO alembic_version (version_num) VALUES ('0807coderef');
    """)
    connection.commit()
    connection.close()


def test_sqlite_document_and_memory_timestamps_accept_inserts_after_full_upgrade(tmp_path, monkeypatch):
    """Fresh SQLite installations must also repair defaults introduced by older revisions."""
    database_path = tmp_path / "all-migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    expected_defaults = {
        "document_directory": {"created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP"},
        "memory_dataset": {"created_at": "CURRENT_TIMESTAMP"},
    }
    for table_name, expected in expected_defaults.items():
        defaults = {
            row[1]: row[4]
            for row in connection.execute(f"PRAGMA table_info({table_name})")
            if row[1] in expected
        }
        assert defaults == expected

    connection.execute(
        "INSERT INTO document_directory (module_type, name, id, project_id) VALUES (?, ?, ?, ?)",
        ("glossary", "terms", "directory-1", "project-1"),
    )
    connection.execute(
        "INSERT INTO memory_dataset (project_id, cognee_dataset_id, id) VALUES (?, ?, ?)",
        ("project-1", "dataset-1", "memory-dataset-1"),
    )
    connection.commit()
    connection.close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    defaults = {
        row[1]: row[4]
        for row in connection.execute("PRAGMA table_info(code_library)")
        if row[1] in {"created_at", "updated_at"}
    }
    assert defaults == {"created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP"}
    connection.execute(
        "INSERT INTO code_library (name, language, package, id, project_id) VALUES (?, ?, ?, ?, ?)",
        ("Runtime", "csharp", "Game.Runtime", "library-1", "project-1"),
    )
    connection.commit()
    connection.close()
