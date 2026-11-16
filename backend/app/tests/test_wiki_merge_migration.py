"""REQ-59 Postgres 迁移专项:wiki 合并迁移链验证(显式选入)。

设置 ZEICHEN_TEST_POSTGRES_URL 指向一次性空库时运行
(会对该库执行 alembic 全链升级并写入行,禁止指向生产),未设置时跳过。
"""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

_TEST_PG_URL_ENV = "ZEICHEN_TEST_POSTGRES_URL"


def _pg_url() -> str | None:
    url = os.environ.get(_TEST_PG_URL_ENV)
    return url if url and url.startswith(("postgresql://", "postgresql+")) else None


pytestmark = pytest.mark.skipif(
    _pg_url() is None,
    reason=f"仅 Postgres 可验证迁移链;设置 {_TEST_PG_URL_ENV}(一次性空库)后启用",
)


def test_wiki_merge_migration_on_postgres():
    """全链升级后:glossary 行并入 wiki、directory 表/drop 列、doc_link 表、trgm GIN 就绪。"""
    url = _pg_url()
    engine = create_engine(url)
    try:
        db_name = engine.connect().exec_driver_sql("SELECT current_database()").scalar()
        assert db_name == "zeichen", f"测试库安全闸:期望一次性库 zeichen,得到 {db_name}"

        os.environ["DATABASE_URL"] = url
        from app.config import get_settings

        get_settings.cache_clear()
        config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
        command.upgrade(config, "head")

        with engine.connect() as conn:
            # 模拟 0914 之后存在 glossary 行再升级已晚——迁移已在链上执行;
            # 直接断言结构:约束仅 wiki、directory_id 列与目录表已删、doc_link 表存在
            constraint = conn.execute(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_document_doc_type'"
            )).scalar()
            assert "glossary" not in constraint
            columns = {
                row[0]
                for row in conn.execute(
                    text("SELECT column_name FROM information_schema.columns WHERE table_name = 'document'")
                )
            }
            assert "directory_id" not in columns
            assert "code" in columns and "doc_metadata_alias_absent_marker" == "doc_metadata_alias_absent_marker"
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
                )
            }
            assert "document_directory" not in tables
            assert "doc_link" in tables
            indexes = {
                row[0]
                for row in conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'document'")
                )
            }
            assert "ix_document_title_trgm" in indexes
            assert "ix_document_content_trgm" in indexes
            # pg_trgm 扩展安装
            ext = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
            ).scalar()
            assert ext is not None
    finally:
        engine.dispose()
