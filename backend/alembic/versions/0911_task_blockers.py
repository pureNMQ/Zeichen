"""task_blocker:任务阻塞依赖边(REQ-7)。

Revision ID: 0911taskblockers
Revises: 0819filterviews
Create Date: 2026-09-11 04:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0911taskblockers"
down_revision = "0819filterviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_blocker",
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocker_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "blocker_id", name="uq_task_blocker_pair"),
    )
    op.create_index("ix_task_blocker_task_id", "task_blocker", ["task_id"])
    op.create_index("ix_task_blocker_blocker_id", "task_blocker", ["blocker_id"])
    op.create_index("ix_task_blocker_project_id", "task_blocker", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_task_blocker_project_id", table_name="task_blocker")
    op.drop_index("ix_task_blocker_blocker_id", table_name="task_blocker")
    op.drop_index("ix_task_blocker_task_id", table_name="task_blocker")
    op.drop_table("task_blocker")
