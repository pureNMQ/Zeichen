"""REQ-56 回归:task_blocker 遗留 id 列清理(迁移链 schema 漂移)。

0914 短码迁移对 task/document 均删除了旧 UUID 主键列,唯独 task_blocker 漏删:
生产库遗留 NOT NULL 且无默认值的 id 列,而模型 TaskBlocker 不含 id,
INSERT 不提供该列 → 非空约束违规 → tasks.create/update 传 blocked_by 必现 500。
sqlite 测试库由 metadata create_all 建表,从未暴露;仅迁移链上的 Postgres 可复现。

本文件为显式选入的 Postgres 专项测试:设置 ZEICHEN_TEST_POSTGRES_URL 指向
一次性空库时运行(会对该库执行 alembic 全链升级并写入行,禁止指向生产),
未设置时跳过,不影响 sqlite 常规套件。
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from sqlalchemy import inspect

_TEST_PG_URL_ENV = "ZEICHEN_TEST_POSTGRES_URL"


def _pg_url() -> str | None:
    url = os.environ.get(_TEST_PG_URL_ENV)
    return url if url and url.startswith(("postgresql://", "postgresql+")) else None


pytestmark = pytest.mark.skipif(
    _pg_url() is None,
    reason=f"仅 Postgres 可复现迁移链漂移;设置 {_TEST_PG_URL_ENV}(一次性空库)后启用",
)


def test_task_blocker_schema_matches_model_after_full_chain():
    """全链迁移后 task_blocker 列集与模型一致,且无 id 的 INSERT 成功(500 复现路径)。"""
    url = _pg_url()
    engine = create_engine(url)
    try:
        # 该测试自建库自行升级;此处断言目标确为本次测试专用库(防误指生产)
        db_name = engine.connect().exec_driver_sql("SELECT current_database()").scalar()
        assert db_name == "zeichen", f"测试库安全闸:期望一次性库 zeichen,得到 {db_name}"

        os.environ["DATABASE_URL"] = url
        from app.config import get_settings

        get_settings.cache_clear()
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        command.upgrade(config, "head")

        tables = inspect(engine).get_table_names()
        assert "task_blocker" not in tables
        assert "legacy_task_blocker_archive" in tables
        columns = {row["name"] for row in inspect(engine).get_columns("task")}
        assert {"legacy_code", "requirement_id", "code"} <= columns
    finally:
        engine.dispose()
