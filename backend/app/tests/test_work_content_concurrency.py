from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Update

from app.errors import AppError
from app.models import Project, Team, User, WorkspaceMember
from app.services.requirements import create_requirement, update_requirement
from app.tests.test_task_claim_concurrency_api import claim_engine  # noqa: F401
from app.v2.work_content_models import WorkVersion


def test_two_editors_cannot_overwrite_one_version(claim_engine):
    with Session(claim_engine) as db:
        team = Team(name="编辑测试")
        user = User(username="editor", password_hash="")
        db.add_all([team, user])
        db.flush()
        project = Project(team_id=team.id, name="并行编辑")
        db.add_all([project, WorkspaceMember(team_id=team.id, user_id=user.id, role="admin")])
        db.flush()
        actor_id, project_id = user.id, project.id
        code = create_requirement(db, user, project.id, "初稿", "原文").code

    ready = Barrier(2, timeout=10)

    def sync(conn, cursor, statement, params, ctx, many):
        stmt = getattr(getattr(ctx, "compiled", None), "statement", None)
        if isinstance(stmt, Update) and stmt.table.name == "requirement":
            ready.wait()

    def edit(body):
        with Session(claim_engine) as db:
            try:
                update_requirement(db, db.get(User, actor_id), code, description=body,
                                   project_id=project_id, expected_version=1)
                return "saved", body
            except AppError as exc:
                return exc.code, body

    event.listen(claim_engine, "before_cursor_execute", sync)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = dict(pool.map(edit, ["甲稿", "乙稿"]))
    finally:
        event.remove(claim_engine, "before_cursor_execute", sync)

    assert set(results) == {"saved", "conflict"}
    with Session(claim_engine) as db:
        revisions = db.scalars(select(WorkVersion.description).where(
            WorkVersion.project_id == project_id, WorkVersion.code == code,
        ).order_by(WorkVersion.version)).all()
        assert revisions == ["原文", results["saved"]]
