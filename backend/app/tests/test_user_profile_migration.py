from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_user_profile_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    db_path = tmp_path / "profile-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    from app.config import get_settings

    get_settings.cache_clear()
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))

    # Only exercise the profile migration's upgrade/downgrade contract.
    command.upgrade(config, "0814usernicknameavatar")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    columns = {column["name"]: column for column in inspect(engine).get_columns("user")}
    assert columns["nickname"]["nullable"] is True
    assert columns["avatar"]["nullable"] is True
    attachment_columns = {column["name"]: column for column in inspect(engine).get_columns("attachment")}
    assert attachment_columns["project_id"]["nullable"] is True

    command.downgrade(config, "0813requirementpending")
    columns = {column["name"] for column in inspect(engine).get_columns("user")}
    assert "nickname" not in columns
    assert "avatar" not in columns
    engine.dispose()
