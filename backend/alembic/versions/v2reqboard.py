"""Introduce requirement dependencies and retain participation after reassignment."""

import sqlalchemy as sa
from alembic import op

revision = "v2reqboard"
down_revision = "v2workcontent"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite" and "code" not in {c["name"] for c in sa.inspect(bind).get_columns("requirement")}:
        return
    parent = ["requirement.project_id", "requirement.code"]
    op.create_table(
        "requirement_blocker",
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("requirement_code", sa.String(16), primary_key=True),
        sa.Column("blocker_code", sa.String(16), primary_key=True),
        sa.ForeignKeyConstraint(["project_id", "requirement_code"], parent, ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id", "blocker_code"], parent, ondelete="CASCADE"),
        sa.CheckConstraint("requirement_code <> blocker_code", name="ck_requirement_blocker_not_self"),
    )
    op.create_index("ix_requirement_blocker_reverse", "requirement_blocker", ["project_id", "blocker_code"])
    op.create_table(
        "requirement_assignee_history",
        sa.Column("project_id", sa.Uuid(), primary_key=True),
        sa.Column("requirement_code", sa.String(16), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.ForeignKeyConstraint(["project_id", "requirement_code"], parent, ondelete="CASCADE"),
    )
    op.execute("INSERT INTO requirement_assignee_history (project_id, requirement_code, user_id) "
               "SELECT DISTINCT project_id, requirement_id, assignee_id FROM task WHERE assignee_id IS NOT NULL")


def downgrade():
    if not sa.inspect(op.get_bind()).has_table("requirement_blocker"):
        return
    op.drop_table("requirement_assignee_history")
    op.drop_table("requirement_blocker")
