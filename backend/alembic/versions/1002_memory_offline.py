"""REQ-57:记忆系统下线——drop 五张记忆/cognee 表,数据不导出不保留。

Revision ID: 1002memoryoffline
Revises: 0917dropblockerid
Create Date: 2026-10-02

下线范围:memory_dataset / memory_grant / memory_improve_job /
cognee_configuration / cognee_restart_job(用户 2026-10-02 已确认直接删除)。
任务原列四张表,memory_grant(记忆互通授权,记忆功能专属数据)一并清理,
与需求「产品与 MCP 中不再存在任何记忆功能」一致。
五表外键均指向 project/user/team,无其他表引用它们,drop 安全。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1002memoryoffline"
down_revision: Union[str, None] = "0917dropblockerid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = (
    "memory_improve_job",
    "memory_dataset",
    "memory_grant",
    "cognee_restart_job",
    "cognee_configuration",
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
            ),
            {"t": table},
        ).scalar() if bind.dialect.name == "postgresql" else bind.execute(
            sa.text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name = :t"
            ),
            {"t": table},
        ).scalar()
        if exists is not None:
            op.drop_table(table)


def downgrade() -> None:
    # 记忆数据已按需求确认直接删除,无导出可恢复;拒绝降级
    raise RuntimeError("记忆系统下线迁移不可降级(数据已确认删除);请回滚至备份")
