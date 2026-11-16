"""REQ-59:wiki 重构为过程记录式 LLM 知识层——数据层迁移。

1. glossary 合并进 wiki:存量 doc_type='glossary' 全部改 'wiki'(TERM-n 短码保留);
   doc_type CHECK 收紧为仅 'wiki';
2. DocumentDirectory 废弃:document.directory_id 列删除、document_directory 表 drop
   (生产实测零使用);
3. 新增 doc_link 表([[双链]]写入时落表;断链行 to_code NULL 保留);
4. PostgreSQL 侧:pg_trgm 扩展 + document.title/content GIN trgm 索引
   (关键词检索候选过滤加速;SQLite 测试环境不适用,跳过)。

说明:常规测试套件在 SQLite 上由 metadata create_all 建表、不经迁移链;
本迁移的 ALTER 细节按 PostgreSQL 生产方言编写(SQLite 分支仅结构性兼容)。

Revision ID: 1007wikimerge
Revises: 1002memoryoffline
Create Date: 2026-10-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1007wikimerge"
down_revision: Union[str, None] = "1002memoryoffline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, name: str) -> bool:
    if bind.dialect.name == "postgresql":
        return bind.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": name},
        ).scalar() is not None
    return bind.execute(
        sa.text("SELECT 1 FROM sqlite_master WHERE type='table' AND name = :t"),
        {"t": name},
    ).scalar() is not None


def _column_exists(bind, table: str, column: str) -> bool:
    if bind.dialect.name == "postgresql":
        return bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar() is not None
    return bind.execute(
        sa.text(f"SELECT 1 FROM pragma_table_info('{table}') WHERE name = :c"),
        {"c": column},
    ).scalar() is not None


def _directory_fk_name(bind) -> str | None:
    """document.directory_id 外键约束名(0914 前老库为复合自命名,直接查 catalog)。"""
    if bind.dialect.name != "postgresql":
        return None
    return bind.execute(
        sa.text(
            "SELECT tc.constraint_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name "
            "AND tc.table_schema = kcu.table_schema "
            "WHERE tc.table_name = 'document' AND tc.constraint_type = 'FOREIGN KEY' "
            "AND kcu.column_name = 'directory_id'"
        )
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1) glossary 合并:存量词条转普通 wiki 页(TERM-n 短码按「永不改变」原则保留)
    bind.execute(sa.text("UPDATE document SET doc_type = 'wiki' WHERE doc_type = 'glossary'"))
    if is_postgres:
        op.drop_constraint("ck_document_doc_type", "document", type_="check")
        op.create_check_constraint(
            "ck_document_doc_type", "document", "doc_type IN ('wiki')"
        )

    # 2) directory_id 列与 document_directory 表废弃
    if _column_exists(bind, "document", "directory_id"):
        # SQLite batch 重建表会重放反射索引,须先删 directory_id 上的索引
        if bind.dialect.name != "postgresql":
            bind.execute(sa.text("DROP INDEX IF EXISTS ix_document_directory_id"))
        fk_name = _directory_fk_name(bind)
        with op.batch_alter_table("document") as batch:
            if is_postgres and fk_name:
                batch.drop_constraint(fk_name, type_="foreignkey")
            batch.drop_column("directory_id")
    if _table_exists(bind, "document_directory"):
        op.drop_table("document_directory")

    # 3) doc_link 表
    op.create_table(
        "doc_link",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("from_code", sa.String(16), nullable=False),
        sa.Column("to_code", sa.String(16), nullable=True),
        sa.Column("raw_text", sa.String(256), nullable=False),
        sa.Column("display_text", sa.String(256), nullable=True),
        sa.Column("section", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "from_code"],
            ["document.project_id", "document.code"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "to_code"],
            ["document.project_id", "document.code"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_doc_link_project_id", "doc_link", ["project_id"])
    op.create_index("ix_doc_link_from_code", "doc_link", ["from_code"])
    op.create_index("ix_doc_link_reverse", "doc_link", ["project_id", "to_code"])

    # 4) pg_trgm + GIN(仅 postgresql;排序在服务端,索引只加速候选过滤)
    if is_postgres:
        bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.create_index(
            "ix_document_title_trgm",
            "document",
            ["title"],
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        )
        op.create_index(
            "ix_document_content_trgm",
            "document",
            ["content"],
            postgresql_using="gin",
            postgresql_ops={"content": "gin_trgm_ops"},
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 4) 撤销 pg_trgm GIN 索引(扩展保留,无害)
    if is_postgres:
        op.drop_index("ix_document_content_trgm", table_name="document")
        op.drop_index("ix_document_title_trgm", table_name="document")

    # 3) drop doc_link 表
    op.drop_index("ix_doc_link_reverse", table_name="doc_link")
    op.drop_index("ix_doc_link_from_code", table_name="doc_link")
    op.drop_index("ix_doc_link_project_id", table_name="doc_link")
    op.drop_table("doc_link")

    # 2) 重建 document_directory 与 document.directory_id(空目录树,词条回根级)
    op.create_table(
        "document_directory",
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("module_type", sa.String(16), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("parent_id", sa.String(16), nullable=True),
        sa.CheckConstraint("module_type IN ('glossary')", name="ck_document_directory_module_type"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["document_directory.project_id", "document_directory.code"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("project_id", "code"),
    )
    op.create_index("ix_document_directory_project_id", "document_directory", ["project_id"])
    op.create_index("ix_document_directory_parent_id", "document_directory", ["parent_id"])
    with op.batch_alter_table("document") as batch:
        batch.add_column(sa.Column("directory_id", sa.String(16), nullable=True))
        batch.create_index("ix_document_directory_id", ["directory_id"])
        batch.create_foreign_key(
            "document_directory_id_fkey",
            "document_directory",
            ["project_id", "directory_id"],
            ["project_id", "code"],
            ondelete="SET NULL",
        )

    # 1) 恢复双模块:TERM-n 短码行回 glossary;CHECK 放宽回 ('wiki', 'glossary')
    # (SQLite 历史链存在 0914 已知漂移:document 无 code 列,此时跳过数据回写)
    if _column_exists(bind, "document", "code"):
        bind.execute(sa.text("UPDATE document SET doc_type = 'glossary' WHERE code LIKE 'TERM-%'"))
    if is_postgres:
        op.drop_constraint("ck_document_doc_type", "document", type_="check")
        op.create_check_constraint(
            "ck_document_doc_type", "document", "doc_type IN ('wiki', 'glossary')"
        )
