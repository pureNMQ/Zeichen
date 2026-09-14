"""ADR 0004:Agent 附属化——user.owner_id + 存量 agent 干净切换。

Revision ID: 0915affiliation
Revises: 0914shortcodes
Create Date: 2026-09-14 00:00:00.000000

存量处置(破坏性,ADR 0004 决策 5,用户 2026-09-14 授权「全量实施+立即存量处置」):
1) 吊销全部存量 agent 的未吊销 key;
2) 软删全部存量 agent user 行(历史活动/评论署名仍可解析);
3) 物理清除存量 agent 的 project_member 授权行。
清单留痕:由部署会话在执行前后 SELECT 导出并写入部署日志(迁移内不落盘)。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0915affiliation"
down_revision: Union[str, None] = "0914shortcodes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 不支持 ALTER 约束,列/FK/CHECK 走 batch 模式( recreates table)
    with op.batch_alter_table("user") as batch:
        batch.add_column(sa.Column("owner_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_user_owner_id_user", "user", ["owner_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_check_constraint(
            "ck_user_owner_only_for_agent", "owner_id IS NULL OR is_agent"
        )
    op.create_index("ix_user_owner_id", "user", ["owner_id"])
    # 每个主人至多一个附属 Agent(部分唯一索引,人类 owner_id 恒 NULL 不受约束)
    op.create_index(
        "uq_user_owner_one_agent",
        "user",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("owner_id IS NOT NULL"),
        sqlite_where=sa.text("owner_id IS NOT NULL"),
    )

    # 存量处置(顺序:先吊销 key,再软删 agent,最后清授权行)
    op.execute(
        sa.text(
            'UPDATE api_key SET revoked_at = CURRENT_TIMESTAMP '
            'WHERE revoked_at IS NULL AND user_id IN '
            '(SELECT id FROM "user" WHERE is_agent AND deleted_at IS NULL)'
        )
    )
    op.execute(
        sa.text(
            'UPDATE "user" SET deleted_at = CURRENT_TIMESTAMP '
            'WHERE is_agent AND deleted_at IS NULL'
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM project_member WHERE user_id IN "
            '(SELECT id FROM "user" WHERE is_agent)'
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Agent 附属化迁移不可降级(ADR 0004:存量 agent 已软删且授权行清零,"
        "无法忠实还原);如需回滚请恢复迁移前数据库备份"
    )
