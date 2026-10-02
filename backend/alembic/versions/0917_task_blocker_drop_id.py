"""REQ-56:清理 task_blocker 遗留的旧 UUID 主键列 id。

Revision ID: 0917dropblockerid
Revises: 0916ownerindex
Create Date: 2026-10-02

0914 短码迁移把 task_blocker 重建为 (project_id, task_id, blocker_id) 复合主键时,
对 task/document 均执行的 DROP COLUMN id 唯独漏掉了 task_blocker:生产库遗留
NOT NULL 且无默认值的 id 列,而模型 TaskBlocker 不含 id,INSERT 不提供该列即
违反非空约束——tasks.create/update 传非空 blocked_by 必现 500(整个事务回滚)。
sqlite 测试库由 metadata create_all 建表,从未暴露该漂移。本迁移删除遗留列,
使 schema 与模型对齐(REQ-49 同类缺陷家族)。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0917dropblockerid"
down_revision: Union[str, None] = "0916ownerindex"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # 测试库(sqlite)由 metadata 建表,无遗留列
        return
    leftover = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'task_blocker' AND column_name = 'id'"
        )
    ).scalar()
    if leftover is not None:
        bind.execute(sa.text("ALTER TABLE task_blocker DROP COLUMN id"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # 测试库(sqlite)从未有过该列,升级时即空操作
        return
    # 旧 id 已无数据来源,忠实恢复不可行;重新加列只会复现 NOT NULL 缺陷,拒绝降级
    raise RuntimeError("task_blocker 遗留 id 列清理不可降级;请回滚至备份")
