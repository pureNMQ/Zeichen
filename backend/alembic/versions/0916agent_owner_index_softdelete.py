"""REQ-51:owner_id 部分唯一索引豁免软删 Agent。

Revision ID: 0916ownerindex
Revises: 0915affiliation
Create Date: 2026-09-16

0915 的索引谓词仅 owner_id IS NOT NULL,软删 Agent 仍占用 owner_id 唯一占位,
与服务层 get_owned_agent(只认未软删)不一致:主人重建附属 Agent 时 INSERT 撞索引
抛 UniqueViolation,POST /api/my-agent 返回 500。本迁移把谓词补齐
deleted_at IS NULL,与模型层 __table_args__ 对齐;存量脏数据(软删行)随谓词变更
自然释放占位,无需数据订正。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0916ownerindex"
down_revision: Union[str, None] = "0915affiliation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LIVE = "owner_id IS NOT NULL AND deleted_at IS NULL"
_PRE_0916 = "owner_id IS NOT NULL"


def _recreate(where: str) -> None:
    op.drop_index("uq_user_owner_one_agent", table_name="user")
    op.create_index(
        "uq_user_owner_one_agent",
        "user",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text(where),
        sqlite_where=sa.text(where),
    )


def upgrade() -> None:
    _recreate(_LIVE)


def downgrade() -> None:
    # 回退到旧谓词;若此时存在同主人的软删+存活附属 Agent,回退会因唯一冲突失败,
    # 须先清理软删行(符合 0915 不可忠实降级的同一取向)
    _recreate(_PRE_0916)
