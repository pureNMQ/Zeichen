"""任务收归需求(ADR 0003):任务必挂需求、任务四态/需求六态、任务评论取消。

- 软删无归属任务(导出清单留痕;发现非取消态存活独立任务则停下人工确认)
- 硬删 target_type=task 的 comment 行
- 存量 verifying 任务统一置 done
- CHECK 约束:task 去 verifying;requirement 增 verifying
- task.requirement_id 收紧 NOT NULL(FK ondelete 随模型改 CASCADE)

Revision ID: 0913taskunderreq
Revises: 0912notifprefs
Create Date: 2026-09-13 03:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0913taskunderreq"
down_revision: Union[str, None] = "0912notifprefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TASK_FOUR_STATES = "'backlog', 'in_progress', 'done', 'cancelled'"
TASK_FIVE_STATES = "'backlog', 'in_progress', 'verifying', 'done', 'cancelled'"
REQ_FIVE_STATES = "'pending', 'backlog', 'in_progress', 'done', 'cancelled'"
REQ_SIX_STATES = "'pending', 'backlog', 'in_progress', 'verifying', 'done', 'cancelled'"


def _now_sql() -> sa.text:
    return sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 无归属任务:导出清单留痕(部署日志) → 非取消态存活独立任务停下人工确认
    #    → 物理删除全部无归属行(requirement_id 收紧 NOT NULL 要求,含此前已软删的)
    orphans = bind.execute(
        sa.text(
            "SELECT id, title, status, project_id, created_at, deleted_at FROM task "
            "WHERE requirement_id IS NULL ORDER BY created_at"
        )
    ).fetchall()
    if orphans:
        print(f"[0913taskunderreq] 无归属任务 {len(orphans)} 条(删除清单,部署日志留痕):")
        for row in orphans:
            state = "已软删" if row[5] is not None else row[2]
            print(f"  - id={row[0]} title={row[1]!r} status={state} project={row[3]} created={row[4]}")
    live_active = [row for row in orphans if row[5] is None and row[2] != "cancelled"]
    if live_active:
        raise RuntimeError(
            f"发现 {len(live_active)} 条非取消态存活独立任务,请人工确认归属后再执行迁移(见上方清单)"
        )
    if orphans:
        removed = bind.execute(
            sa.text("DELETE FROM task WHERE requirement_id IS NULL")
        ).rowcount
        print(f"[0913taskunderreq] 物理删除无归属任务 {removed} 行")

    # 2) 任务评论硬删(评论区取消,ADR 0003 决策 5)
    deleted_comments = bind.execute(
        sa.text("DELETE FROM comment WHERE target_type = 'task'")
    ).rowcount
    print(f"[0913taskunderreq] 硬删任务评论 {deleted_comments} 行")

    # 3) 存量 verifying 任务 → done(先迁移数据再收紧 CHECK)
    bind.execute(sa.text("UPDATE task SET status = 'done' WHERE status = 'verifying'"))

    # 4) CHECK 约束与 NOT NULL 收紧
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("task") as batch_op:
            batch_op.drop_constraint("ck_task_status", type_="check")
        with op.batch_alter_table("task") as batch_op:
            batch_op.create_check_constraint("ck_task_status", f"status IN ({TASK_FOUR_STATES})")
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.drop_constraint("ck_requirement_status", type_="check")
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.create_check_constraint(
                "ck_requirement_status", f"status IN ({REQ_SIX_STATES})"
            )
        with op.batch_alter_table("task") as batch_op:
            batch_op.alter_column("requirement_id", existing_type=sa.Uuid(), nullable=False)
    else:
        op.drop_constraint("ck_task_status", "task", type_="check")
        op.create_check_constraint("ck_task_status", "task", f"status IN ({TASK_FOUR_STATES})")
        op.drop_constraint("ck_requirement_status", "requirement", type_="check")
        op.create_check_constraint(
            "ck_requirement_status", "requirement", f"status IN ({REQ_SIX_STATES})"
        )
        # NOT NULL + ondelete CASCADE:需求硬删(物理清理)级联任务,而非 SET NULL 违反 NOT NULL
        op.drop_constraint("task_requirement_id_fkey", "task", type_="foreignkey")
        op.alter_column("task", "requirement_id", existing_type=sa.Uuid(), nullable=False)
        op.create_foreign_key(
            "task_requirement_id_fkey",
            "task",
            "requirement",
            ["requirement_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    """结构可回退;数据变更(软删清单/评论硬删/verifying→done)不自动恢复。"""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("task") as batch_op:
            batch_op.alter_column("requirement_id", existing_type=sa.Uuid(), nullable=True)
        with op.batch_alter_table("task") as batch_op:
            batch_op.drop_constraint("ck_task_status", type_="check")
        with op.batch_alter_table("task") as batch_op:
            batch_op.create_check_constraint("ck_task_status", f"status IN ({TASK_FIVE_STATES})")
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.drop_constraint("ck_requirement_status", type_="check")
        with op.batch_alter_table("requirement") as batch_op:
            batch_op.create_check_constraint(
                "ck_requirement_status", f"status IN ({REQ_FIVE_STATES})"
            )
    else:
        op.drop_constraint("task_requirement_id_fkey", "task", type_="foreignkey")
        op.alter_column("task", "requirement_id", existing_type=sa.Uuid(), nullable=True)
        op.create_foreign_key(
            "task_requirement_id_fkey",
            "task",
            "requirement",
            ["requirement_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.drop_constraint("ck_task_status", "task", type_="check")
        op.create_check_constraint("ck_task_status", "task", f"status IN ({TASK_FIVE_STATES})")
        op.drop_constraint("ck_requirement_status", "requirement", type_="check")
        op.create_check_constraint(
            "ck_requirement_status", "requirement", f"status IN ({REQ_FIVE_STATES})"
        )
