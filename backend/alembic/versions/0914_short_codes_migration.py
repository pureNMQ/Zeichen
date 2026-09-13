"""实体短码迁移(ADR 0002,REQ 4eca5928):五类实体回填短码并切换复合主键。

执行顺序(必须先于新代码上线):
1. 五类实体按 (project_id, created_at, 旧UUID字典序) 排序回填 code(每项目每类型从 1 起);
2. 初始化计数器为各项目各类型最大序号;
3. 改写外键与多态引用(task.requirement_id、task_blocker、document 父子/目录/版本、
   comment/activity/reference/notification/entity_watch/attachment 的 target_id、reference from/to);
4. 收紧 schema:五类表删 UUID 主键列、建 (project_id, code) 复合主键、复合外键;
   多态表 target_id 改 String;task.requirement_id 改 String NOT NULL。

 Revision ID: 0914shortcodes
 Revises: 0913taskunderreq
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0914shortcodes"
down_revision: Union[str, None] = "0913taskunderreq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 实体表 → (类型键, 前缀);glossary 按前缀 TERM 计数
_ENTITIES = {
    "requirement": ("requirement", "REQ"),
    "task": ("task", "TASK"),
    "document_directory": ("document_directory", "DIR"),
}
# document 特殊:wiki → DOC,glossary → TERM,分开计数
_DOCUMENT_TYPES = (("wiki", "DOC"), ("glossary", "TERM"))

_POLY_TABLES = ("comment", "activity", "notification", "entity_watch", "attachment")


def _add_code_column(bind, table: str) -> None:
    cols = {r[0] for r in bind.execute(
        sa.text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'code'"
        ),
        {"t": table},
    ).fetchall()}
    if not cols:
        bind.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN code VARCHAR(16)"))


def _backfill_codes(bind) -> None:
    """为五类实体回填 code(临时列),并初始化计数器。"""
    for table, (entity_type, prefix) in _ENTITIES.items():
        _add_code_column(bind, table)
        _backfill_table(bind, table, entity_type, prefix, extra_type_col=None)
    _add_code_column(bind, "document")
    for doc_type, prefix in _DOCUMENT_TYPES:
        _backfill_table(bind, "document", f"document:{doc_type}", prefix, extra_type_col=doc_type)


def _backfill_table(bind, table: str, entity_type: str, prefix: str, extra_type_col) -> None:
    if extra_type_col is None:
        rows = bind.execute(
            sa.text(
                f"SELECT id, project_id FROM {table} "
                f"ORDER BY project_id, created_at, id"
            )
        ).fetchall()
        counters: dict = {}
        for old_id, project_id in rows:
            counters.setdefault(project_id, 0)
            counters[project_id] += 1
            bind.execute(
                sa.text(f"UPDATE {table} SET code = :code WHERE id = :id"),
                {"code": f"{prefix}-{counters[project_id]}", "id": old_id},
            )
        for project_id, last in counters.items():
            bind.execute(
                sa.text(
                    "INSERT INTO short_code_counter (project_id, entity_type, last_seq, "
                    "created_at, updated_at) VALUES (:p, :t, :s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"p": project_id, "t": entity_type, "s": last},
            )
    else:
        rows = bind.execute(
            sa.text(
                f"SELECT id, project_id FROM document WHERE doc_type = :dt "
                f"ORDER BY project_id, created_at, id"
            ),
            {"dt": extra_type_col},
        ).fetchall()
        counters: dict = {}
        for old_id, project_id in rows:
            counters.setdefault(project_id, 0)
            counters[project_id] += 1
            bind.execute(
                sa.text("UPDATE document SET code = :code WHERE id = :id"),
                {"code": f"{prefix}-{counters[project_id]}", "id": old_id},
            )
        for project_id, last in counters.items():
            bind.execute(
                sa.text(
                    "INSERT INTO short_code_counter (project_id, entity_type, last_seq, "
                    "created_at, updated_at) VALUES (:p, :t, :s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"p": project_id, "t": entity_type, "s": last},
            )


def _code_of(bind, table: str, old_id) -> str:
    return bind.execute(
        sa.text(f"SELECT code FROM {table} WHERE id = :id"), {"id": old_id}
    ).scalar_one()


def _rewrite_references(bind) -> None:
    # 0) 先删所有涉及被改写列的 FK(否则 UUID FK 会拒绝短码/类型变更)
    bind.execute(sa.text("ALTER TABLE task DROP CONSTRAINT IF EXISTS task_requirement_id_fkey"))
    bind.execute(sa.text("ALTER TABLE task_blocker DROP CONSTRAINT IF EXISTS task_blocker_task_id_fkey"))
    bind.execute(sa.text("ALTER TABLE task_blocker DROP CONSTRAINT IF EXISTS task_blocker_blocker_id_fkey"))
    bind.execute(sa.text(
        "ALTER TABLE document DROP CONSTRAINT IF EXISTS document_parent_id_fkey, "
        "DROP CONSTRAINT IF EXISTS fk_document_parent_id, "
        "DROP CONSTRAINT IF EXISTS document_directory_id_fkey, "
        "DROP CONSTRAINT IF EXISTS fk_document_directory_id"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document_directory DROP CONSTRAINT IF EXISTS document_directory_parent_id_fkey, "
        "DROP CONSTRAINT IF EXISTS fk_document_directory_parent"
    ))
    bind.execute(sa.text("ALTER TABLE document_version DROP CONSTRAINT IF EXISTS document_version_document_id_fkey"))
    # ck_reference_not_self 混合 from_id<>to_id 比较,列放宽期间必须先删、改写完成后再重建
    bind.execute(sa.text("ALTER TABLE reference DROP CONSTRAINT IF EXISTS ck_reference_not_self"))
    bind.execute(sa.text("ALTER TABLE document_version DROP CONSTRAINT IF EXISTS uq_document_version_doc_no"))

    # 0.5) 全部被改写列先放宽为文本(UUID 列拒绝短码)
    bind.execute(sa.text(
        "ALTER TABLE task ALTER COLUMN requirement_id DROP DEFAULT"
    ))
    bind.execute(sa.text(
        "ALTER TABLE task ALTER COLUMN requirement_id TYPE VARCHAR(36) USING requirement_id::text"
    ))
    bind.execute(sa.text(
        "ALTER TABLE task_blocker ALTER COLUMN task_id TYPE VARCHAR(36) USING task_id::text"
    ))
    bind.execute(sa.text(
        "ALTER TABLE task_blocker ALTER COLUMN blocker_id TYPE VARCHAR(36) USING blocker_id::text"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document ALTER COLUMN parent_id TYPE VARCHAR(36) USING parent_id::text"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document ALTER COLUMN directory_id TYPE VARCHAR(36) USING directory_id::text"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document_directory ALTER COLUMN parent_id TYPE VARCHAR(36) USING parent_id::text"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document_version ALTER COLUMN document_id TYPE VARCHAR(36) USING document_id::text"
    ))
    for table in _POLY_TABLES:
        bind.execute(sa.text(
            f"ALTER TABLE {table} ALTER COLUMN target_id TYPE VARCHAR(36) USING target_id::text"
        ))
    for col in ("from_id", "to_id"):
        bind.execute(sa.text(
            f"ALTER TABLE reference ALTER COLUMN {col} TYPE VARCHAR(36) USING {col}::text"
        ))
    for old_rid, new_code in bind.execute(sa.text("SELECT id, code FROM requirement")).fetchall():
        bind.execute(
            sa.text("UPDATE task SET requirement_id = :code WHERE requirement_id = CAST(:rid AS VARCHAR)"),
            {"code": new_code, "rid": str(old_rid)},
        )
    # 2) task_blocker 两端
    for old_tid, new_code in bind.execute(sa.text("SELECT id, code FROM task")).fetchall():
        bind.execute(
            sa.text("UPDATE task_blocker SET task_id = :code WHERE task_id = CAST(:tid AS VARCHAR)"),
            {"code": new_code, "tid": old_tid},
        )
        bind.execute(
            sa.text("UPDATE task_blocker SET blocker_id = :code WHERE blocker_id = CAST(:tid AS VARCHAR)"),
            {"code": new_code, "tid": old_tid},
        )
    # 2.5) document_version:先补 project_id(利用仍存在的 document.id)并改写 document_id
    bind.execute(sa.text("ALTER TABLE document_version ADD COLUMN IF NOT EXISTS project_id UUID"))
    bind.execute(sa.text(
        "UPDATE document_version SET document_id = CAST(document_id AS VARCHAR)"
    ))
    bind.execute(sa.text(
        "UPDATE document_version dv SET document_id = d.code, project_id = d.project_id "
        "FROM document d WHERE CAST(d.id AS VARCHAR) = dv.document_id"
    ))
    # 3) document 父子/目录/版本
    for old_did, new_code in bind.execute(sa.text("SELECT id, code FROM document")).fetchall():
        bind.execute(
            sa.text("UPDATE document SET parent_id = :code WHERE parent_id = CAST(:did AS VARCHAR)"),
            {"code": new_code, "did": old_did},
        )
        bind.execute(
            sa.text("UPDATE document_version SET document_id = :code WHERE document_id = CAST(:did AS VARCHAR)"),
            {"code": new_code, "did": old_did},
        )
    for old_dir, new_code in bind.execute(
        sa.text("SELECT id, code FROM document_directory")
    ).fetchall():
        bind.execute(
            sa.text("UPDATE document SET directory_id = :code WHERE directory_id = CAST(:did AS VARCHAR)"),
            {"code": new_code, "did": old_dir},
        )
        bind.execute(
            sa.text("UPDATE document_directory SET parent_id = :code WHERE parent_id = CAST(:did AS VARCHAR)"),
            {"code": new_code, "did": old_dir},
        )
    # 4) 多态表 target_id:requirement/task/document → 短码;project/repository 保 UUID 文本
    code_maps = {
        "requirement": dict(bind.execute(sa.text("SELECT id, code FROM requirement")).fetchall()),
        "task": dict(bind.execute(sa.text("SELECT id, code FROM task")).fetchall()),
        "document": dict(bind.execute(sa.text("SELECT id, code FROM document")).fetchall()),
    }
    for table in _POLY_TABLES + ("reference",):
        for ttype, mapping in code_maps.items():
            col = "target_id"
            if table == "reference":
                col = "from_id" if False else col  # 双列分别处理
            if table != "reference":
                for old_id, new_code in mapping.items():
                    bind.execute(
                        sa.text(
                            f"UPDATE {table} SET {col} = :code "
                            f"WHERE target_type = :tt AND {col} = CAST(:oid AS VARCHAR)"
                        ),
                        {"code": new_code, "tt": ttype, "oid": str(old_id)},
                    )
    # 4.5) 重建引用防自环 CHECK(列已统一 varchar)
    bind.execute(sa.text(
        "ALTER TABLE reference ADD CONSTRAINT ck_reference_not_self "
        "CHECK (from_type <> to_type OR from_id <> to_id)"
    ))
    # 5) reference from_id/to_id
    for ttype, mapping in code_maps.items():
        col = "from_id"
        for old_id, new_code in mapping.items():
            bind.execute(
                sa.text(
                    f"UPDATE reference SET {col} = :code WHERE from_type = :tt AND {col} = CAST(:oid AS VARCHAR)"
                ),
                {"code": new_code, "tt": ttype, "oid": str(old_id)},
            )
        col = "to_id"
        for old_id, new_code in mapping.items():
            bind.execute(
                sa.text(
                    f"UPDATE reference SET {col} = :code WHERE to_type = :tt AND {col} = CAST(:oid AS VARCHAR)"
                ),
                {"code": new_code, "tt": ttype, "oid": str(old_id)},
            )


def _ensure_project_columns(bind) -> None:
    """entity_watch/notification 若缺 project_id 冗余列则补齐并回填。"""
    watch_cols = {r[0] for r in bind.execute(
        sa.text("SELECT column_name FROM information_schema.columns WHERE table_name='entity_watch'")
    ).fetchall()}
    if "project_id" not in watch_cols:
        bind.execute(sa.text("ALTER TABLE entity_watch ADD COLUMN project_id UUID"))
        bind.execute(
            sa.text(
                "UPDATE entity_watch SET project_id = ("
                " SELECT p.id FROM project p WHERE p.id = entity_watch.project_id)"
            )
        )


def _upgrade_postgres(bind) -> None:
    # 计数器表先建(回填时写入初始序号)
    bind.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS short_code_counter (
            project_id UUID NOT NULL REFERENCES project(id) ON DELETE CASCADE,
            entity_type VARCHAR(24) NOT NULL,
            last_seq INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (project_id, entity_type)
        )
    """))
    _backfill_codes(bind)
    probe = bind.execute(sa.text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='requirement' AND column_name IN ('code','id') "
        "ORDER BY column_name"
    )).fetchall()
    print(f"[0914 probe] requirement cols after backfill: {probe}")
    probe2 = bind.execute(sa.text(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='task' AND column_name='requirement_id'"
    )).fetchall()
    print(f"[0914 probe] task.requirement_id before rewrite: {probe2}")
    _rewrite_references(bind)

    # --- requirement ---
    bind.execute(sa.text("ALTER TABLE requirement DROP CONSTRAINT requirement_pkey"))
    bind.execute(sa.text("ALTER TABLE requirement DROP CONSTRAINT requirement_project_id_fkey"))
    bind.execute(sa.text("ALTER TABLE task DROP CONSTRAINT IF EXISTS task_requirement_id_fkey"))
    bind.execute(sa.text("ALTER TABLE requirement ALTER COLUMN code SET NOT NULL"))
    bind.execute(sa.text("ALTER TABLE requirement DROP COLUMN id"))
    bind.execute(sa.text(
        "ALTER TABLE requirement ADD PRIMARY KEY (project_id, code)"
    ))
    bind.execute(sa.text(
        "ALTER TABLE requirement ADD CONSTRAINT requirement_project_id_fkey "
        "FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE"
    ))
    bind.execute(sa.text("CREATE INDEX ix_requirement_code ON requirement (code)"))
    # task.requirement_id → 复合外键
    bind.execute(sa.text(
        "ALTER TABLE task ADD CONSTRAINT task_requirement_id_fkey FOREIGN KEY "
        "(project_id, requirement_id) REFERENCES requirement (project_id, code) ON DELETE CASCADE"
    ))

    # --- task ---
    bind.execute(sa.text("ALTER TABLE task DROP CONSTRAINT task_pkey"))
    bind.execute(sa.text("ALTER TABLE task DROP CONSTRAINT task_project_id_fkey"))
    bind.execute(sa.text("ALTER TABLE task ALTER COLUMN code SET NOT NULL"))
    bind.execute(sa.text("ALTER TABLE task DROP COLUMN id"))
    bind.execute(sa.text("ALTER TABLE task ADD PRIMARY KEY (project_id, code)"))
    bind.execute(sa.text(
        "ALTER TABLE task ADD CONSTRAINT task_project_id_fkey "
        "FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE"
    ))
    bind.execute(sa.text("CREATE INDEX ix_task_code ON task (code)"))

    # --- task_blocker:重建为 (project_id, task_id, blocker_id) 复合主键 ---
    bind.execute(sa.text("ALTER TABLE task_blocker DROP CONSTRAINT task_blocker_pkey"))
    bind.execute(sa.text("ALTER TABLE task_blocker DROP CONSTRAINT uq_task_blocker_pair"))
    bind.execute(sa.text("ALTER TABLE task_blocker DROP CONSTRAINT IF EXISTS task_blocker_task_id_fkey"))
    bind.execute(sa.text("ALTER TABLE task_blocker DROP CONSTRAINT IF EXISTS task_blocker_blocker_id_fkey"))
    bind.execute(sa.text(
        "UPDATE task_blocker SET project_id = project_id WHERE project_id IS NOT NULL"
    ))
    bind.execute(sa.text("ALTER TABLE task_blocker ADD PRIMARY KEY (project_id, task_id, blocker_id)"))
    bind.execute(sa.text(
        "ALTER TABLE task_blocker ADD CONSTRAINT uq_task_blocker_pair UNIQUE (project_id, task_id, blocker_id)"
    ))
    bind.execute(sa.text(
        "ALTER TABLE task_blocker ADD CONSTRAINT task_blocker_task_id_fkey FOREIGN KEY "
        "(project_id, task_id) REFERENCES task (project_id, code) ON DELETE CASCADE"
    ))
    bind.execute(sa.text(
        "ALTER TABLE task_blocker ADD CONSTRAINT task_blocker_blocker_id_fkey FOREIGN KEY "
        "(project_id, blocker_id) REFERENCES task (project_id, code) ON DELETE CASCADE"
    ))

    # --- document ---
    bind.execute(sa.text("ALTER TABLE document DROP CONSTRAINT document_pkey"))
    bind.execute(sa.text("ALTER TABLE document DROP CONSTRAINT document_project_id_fkey"))
    bind.execute(sa.text(
        "ALTER TABLE document DROP CONSTRAINT IF EXISTS document_parent_id_fkey, "
        "DROP CONSTRAINT IF EXISTS fk_document_parent_id, "
        "DROP CONSTRAINT IF EXISTS document_directory_id_fkey, "
        "DROP CONSTRAINT IF EXISTS fk_document_directory_id"
    ))
    bind.execute(sa.text("ALTER TABLE document ALTER COLUMN code SET NOT NULL"))
    bind.execute(sa.text("ALTER TABLE document DROP COLUMN id"))
    bind.execute(sa.text("ALTER TABLE document ADD PRIMARY KEY (project_id, code)"))
    bind.execute(sa.text(
        "ALTER TABLE document ADD CONSTRAINT document_project_id_fkey "
        "FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document ADD CONSTRAINT document_parent_id_fkey FOREIGN KEY "
        "(project_id, parent_id) REFERENCES document (project_id, code) ON DELETE SET NULL"
    ))
    bind.execute(sa.text("CREATE INDEX ix_document_code ON document (code)"))

    # --- document_directory ---
    bind.execute(sa.text("ALTER TABLE document_directory DROP CONSTRAINT document_directory_pkey"))
    bind.execute(sa.text("ALTER TABLE document_directory DROP CONSTRAINT document_directory_project_id_fkey"))
    bind.execute(sa.text(
        "ALTER TABLE document_directory DROP CONSTRAINT IF EXISTS document_directory_parent_id_fkey, "
        "DROP CONSTRAINT IF EXISTS fk_document_directory_parent"
    ))
    bind.execute(sa.text("ALTER TABLE document_directory ALTER COLUMN code SET NOT NULL"))
    bind.execute(sa.text("ALTER TABLE document_directory DROP COLUMN id"))
    bind.execute(sa.text("ALTER TABLE document_directory ADD PRIMARY KEY (project_id, code)"))
    bind.execute(sa.text(
        "ALTER TABLE document_directory ADD CONSTRAINT document_directory_project_id_fkey "
        "FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document_directory ADD CONSTRAINT document_directory_parent_id_fkey FOREIGN KEY "
        "(project_id, parent_id) REFERENCES document_directory (project_id, code) ON DELETE SET NULL"
    ))
    bind.execute(sa.text("CREATE INDEX ix_document_directory_code ON document_directory (code)"))
    # 目录表主键就绪后,补 document.directory_id 复合外键
    bind.execute(sa.text(
        "ALTER TABLE document ADD CONSTRAINT document_directory_id_fkey FOREIGN KEY "
        "(project_id, directory_id) REFERENCES document_directory (project_id, code) ON DELETE SET NULL"
    ))

    # --- document_version ---
    bind.execute(sa.text("ALTER TABLE document_version DROP CONSTRAINT IF EXISTS document_version_pkey"))
    bind.execute(sa.text("ALTER TABLE document_version DROP CONSTRAINT IF EXISTS document_version_document_id_fkey"))
    bind.execute(sa.text("ALTER TABLE document_version DROP CONSTRAINT IF EXISTS uq_document_version_doc_no"))
    bind.execute(sa.text("ALTER TABLE document_version DROP CONSTRAINT IF EXISTS uq_document_version_doc_no2"))
    bind.execute(sa.text("ALTER TABLE document_version ADD COLUMN IF NOT EXISTS project_id UUID"))
    bind.execute(sa.text("ALTER TABLE document_version ALTER COLUMN project_id SET NOT NULL"))
    bind.execute(sa.text(
        "ALTER TABLE document_version ADD CONSTRAINT document_version_document_id_fkey FOREIGN KEY "
        "(project_id, document_id) REFERENCES document (project_id, code) ON DELETE CASCADE"
    ))
    bind.execute(sa.text(
        "ALTER TABLE document_version ADD CONSTRAINT uq_document_version_doc_no "
        "UNIQUE (project_id, document_id, version_no)"
    ))
    bind.execute(sa.text("CREATE INDEX ix_document_version_project_id ON document_version (project_id)"))

    # entity_watch/notification 的 project_id 冗余(缺则补)
    _ensure_project_columns(bind)
    bind.execute(sa.text(
        "ALTER TABLE entity_watch ALTER COLUMN target_id TYPE VARCHAR(36) USING target_id::text"
    ))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # 测试库(sqlite)由 metadata 建表,不走结构迁移
        return
    _upgrade_postgres(bind)


def downgrade() -> None:
    """不提供降级:UUID 主键已删除,旧标识不可恢复(按 ADR 0002 彻底废弃)。"""
    raise RuntimeError("短码迁移不可降级(ADR 0002:UUID 彻底废弃);请回滚至备份")
