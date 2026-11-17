"""Exercise a real claim race through authenticated HTTP requests.

Set ZEICHEN_TEST_CLAIM_POSTGRES_URL to the local disposable database
zeichen_claim_test to run the same race on PostgreSQL as well as SQLite.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.sql.dml import Update

from app.db import get_db
from app.main import app
from app.models import Activity, Base, Project, ProjectMember, Requirement, Task, Team, User, WorkspaceMember
from app.security import hash_password
from app.tests.conftest import login
from app.v2.timeline_models import TimelineEntry


@pytest.fixture(params=("sqlite", "postgresql"))
def claim_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{(tmp_path / 'claim.db').as_posix()}")
        try:
            Base.metadata.create_all(engine)
            yield engine
        finally:
            engine.dispose()
        return

    configured = os.environ.get("ZEICHEN_TEST_CLAIM_POSTGRES_URL")
    if not configured:
        pytest.skip("Set ZEICHEN_TEST_CLAIM_POSTGRES_URL for the disposable local PostgreSQL test database")
    url = make_url(configured)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.database == "zeichen_claim_test" and not url.query
    schema = f"race_{uuid4().hex}"
    control = create_engine(url)
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    try:
        with control.begin() as connection:
            connection.execute(CreateSchema(schema))
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        control.dispose()


def test_two_editors_race_to_claim_and_only_one_wins(claim_engine, monkeypatch):
    usernames = ("claim-editor-one", "claim-editor-two")
    password = "synthetic-claim-password"
    with Session(claim_engine) as db, db.begin():
        team = Team(name="Claim race")
        users = [User(username=name, password_hash=hash_password(password)) for name in usernames]
        db.add_all([team, *users])
        db.flush()
        project = Project(team_id=team.id, name="Claim race")
        db.add(project)
        db.flush()
        project_id = project.id
        principal_ids = [user.id for user in users]
        for user in users:
            db.add(WorkspaceMember(team_id=team.id, user_id=user.id, role="member"))
            db.add(ProjectMember(project_id=project_id, user_id=user.id, role="editor"))
        db.add(Requirement(project_id=project_id, code="REQ-1", title="Claim once", status="backlog"))
        db.flush()
        db.add(Task(project_id=project_id, code="TASK-1", requirement_id="REQ-1", title="Unassigned task", status="backlog"))

    def request_db():
        with Session(claim_engine) as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, request_db)
    params = {"project_id": str(project_id)}
    url = "/api/tasks/TASK-1"
    ready_to_write = Barrier(2, timeout=10)
    claim_connections = []

    def synchronize_writes(conn, cursor, sql, params, context, executemany):
        statement = context.compiled.statement if context.compiled is not None else None
        if isinstance(statement, Update) and statement.table.name == Task.__tablename__:
            claim_connections.append(conn.connection.driver_connection)
            # Synchronize only the last step before the database writes. Auth,
            # permission checks, the row lookup, and both UPDATEs run normally.
            ready_to_write.wait()

    with TestClient(app) as first, TestClient(app) as second:
        for client, username in zip((first, second), usernames, strict=True):
            login(client, username, password)
        event.listen(claim_engine, "before_cursor_execute", synchronize_writes)
        try:
            with ThreadPoolExecutor(max_workers=2) as workers:
                attempts = [workers.submit(client.post, f"{url}/claim", params=params) for client in (first, second)]
                responses = [attempt.result(timeout=20) for attempt in attempts]
        finally:
            event.remove(claim_engine, "before_cursor_execute", synchronize_writes)

        assert len(claim_connections) == 2 and claim_connections[0] is not claim_connections[1]
        assert sorted(response.status_code for response in responses) == [200, 409], [r.json() for r in responses]
        winner_index = next(index for index, response in enumerate(responses) if response.status_code == 200)
        winner_id = principal_ids[winner_index]
        assert responses[winner_index].json()["assignee_id"] == str(winner_id)
        loser = responses[1 - winner_index].json()
        assert loser["code"] == "conflict"
        if claim_engine.dialect.name == "postgresql":
            assert loser["message"] == "任务已被认领"
        persisted = first.get(url, params=params)
        assert persisted.status_code == 200 and persisted.json()["assignee_id"] == str(winner_id)

    with Session(claim_engine) as db:
        claim_activity = db.scalars(select(Activity.actor_id).where(
            Activity.project_id == project_id, Activity.target_id == "TASK-1", Activity.action == "claim",
        )).all()
        assert claim_activity == [winner_id]
        claim_events = db.scalars(select(TimelineEntry).where(
            TimelineEntry.project_id == project_id, TimelineEntry.source_task_code == "TASK-1",
            TimelineEntry.event_type == "task.claimed",
        )).all()
        assert len(claim_events) == 1 and claim_events[0].actor_id == winner_id
        assert claim_events[0].event_data == {"before": None, "after": str(winner_id)}
