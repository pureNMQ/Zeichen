from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.errors import AppError
from app.models import Project, ProjectMember, Requirement, Task
from app.services import requirements, tasks
from app.v2 import timeline
from app.v2.resource_refs import ResourceKind, ResourceRef
from app.v2.timeline_models import TimelineEntry

from .conftest import login


def test_web_reject_returns_to_backlog_and_records_reason_once(client, world, scopes):
    scope, _, _ = scopes
    login(client, "admin", "admin-pass-1")
    path = f"/api{scope.path}"
    rejection = {"reason": "补充键盘回归用例", "request_id": str(uuid4())}
    assert client.post(path + "/reject", json=rejection).status_code == 409
    assert client.post(path + "/status", json={"status": "verifying"}).status_code == 200
    response = client.post(path + "/reject", json=rejection)
    assert response.status_code == 200, response.text
    assert client.get(path).json()["status"] == "backlog"
    assert client.post(path + "/reject", json=rejection).json() == response.json()
    assert client.post(path + "/reject", json={**rejection, "reason": "不同内容"}).status_code == 409
    assert client.post(path + "/reject", json={**rejection, "request_id": str(uuid4())}).status_code == 409
    rows = client.get(path + "/timeline", params={"keyword": rejection["reason"]}).json()["items"]
    assert [(row["id"], row["body_preview"]) for row in rows] == [(response.json()["entry_id"], "打回：补充键盘回归用例")]
    systems = client.get(path + "/timeline", params={"kind": "system"}).json()["items"]
    assert sum(row["event_data"]["after"] == "backlog" for row in systems) == 1


def test_web_reject_rolls_back_status_and_receipt_if_reason_write_fails(client, world, scopes, monkeypatch):
    from app.errors import conflict

    scope, _, _ = scopes
    login(client, "admin", "admin-pass-1")
    path = f"/api{scope.path}"
    assert client.post(path + "/status", json={"status": "verifying"}).status_code == 200
    rejection = {"reason": "重试验收", "request_id": str(uuid4())}

    def fail(*args, **kwargs):
        raise conflict("模拟时间轴写入失败")

    with monkeypatch.context() as patch:
        patch.setattr(requirements, "record_manual_entry", fail)
        assert client.post(path + "/reject", json=rejection).status_code == 409
    assert client.get(path).json()["status"] == "verifying"
    assert len(client.get(path + "/timeline").json()["items"]) == 1
    assert client.post(path + "/reject", json=rejection).status_code == 200


@pytest.fixture
def scopes(db, world):
    another = Project(team_id=world["team"].id, name="other")
    db.add(another)
    db.flush()
    own = world["project"].id
    db.add_all([
        Requirement(project_id=own, code="REQ-1", title="第一项", status="backlog"),
        Requirement(project_id=own, code="REQ-2", title="第二项", status="backlog"),
        Requirement(project_id=another.id, code="REQ-1", title="无权同码", status="backlog"),
    ])
    db.commit()
    return tuple(ResourceRef(project, ResourceKind.REQUIREMENT, code) for project, code in [
        (own, "REQ-1"), (own, "REQ-2"), (another.id, "REQ-1"),
    ])


def assert_code(code, action):
    with pytest.raises(AppError) as result:
        action()
    assert result.value.code == code


def test_append_retries_reapply_authorization_and_keep_actual_agent_actor(db, world, scopes):
    scope, _, hidden = scopes
    request_id = uuid4()
    agent = world["agent"]
    receipt = timeline.append_entry(db, agent, scope, request_id=request_id, body="hello\r\nworld")
    db.commit()
    assert timeline.append_entry(db, agent, scope, request_id=request_id, body="hello\nworld") == receipt
    assert db.scalar(select(func.count()).select_from(TimelineEntry)) == 1
    detail = timeline.get_entry(db, world["member"], scope, UUID(receipt["entry_id"]))
    assert detail["actor_id"] == str(agent.id)
    assert detail["body"] == "hello\nworld"
    assert_code("conflict", lambda: timeline.append_entry(
        db, agent, scope, request_id=request_id, body="different request"
    ))
    assert_code("not_found", lambda: timeline.list_entries(db, agent, hidden))
    membership = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == scope.project_id, ProjectMember.user_id == agent.owner_id
    ))
    db.delete(membership)
    db.commit()
    assert_code("not_found", lambda: timeline.append_entry(
        db, agent, scope, request_id=request_id, body="hello\nworld"
    ))


def test_revision_and_withdrawal_preserve_original_and_reply(db, world, scopes):
    scope, another_requirement, another_project = scopes
    editor, owner, reader = world["agent"], world["admin"], world["member"]
    parent = UUID(timeline.append_entry(db, editor, scope, request_id=uuid4(), body="original")["entry_id"])
    reply = UUID(timeline.append_entry(
        db, owner, scope, request_id=uuid4(), body="reply", reply_to=parent
    )["entry_id"])
    db.commit()
    for wrong_scope in (another_requirement, another_project):
        assert_code("not_found", lambda: timeline.append_entry(
            db, owner, wrong_scope, request_id=uuid4(), body="wrong", reply_to=parent
        ))
        db.rollback()
    assert_code("permission_denied", lambda: timeline.revise_entry(
        db, reader, scope, parent, request_id=uuid4(), expected_version=1, body="blocked",
    ))
    assert_code("invalid_request", lambda: timeline.revise_entry(
        db, owner, scope, parent, request_id=uuid4(), expected_version=1, body="missing reason",
    ))
    change = uuid4()
    revision = timeline.revise_entry(
        db, editor, scope, parent, request_id=change, expected_version=1, body="current",
    )
    db.commit()
    assert revision["version"] == 2
    assert timeline.revise_entry(
        db, editor, scope, parent, request_id=change, expected_version=1, body="current",
    ) == revision
    assert_code("conflict", lambda: timeline.withdraw_entry(
        db, owner, scope, parent, request_id=uuid4(), expected_version=1, reason="stale",
    ))
    db.rollback()
    timeline.withdraw_entry(
        db, owner, scope, parent, request_id=uuid4(), expected_version=2, reason="  resolved  ",
    )
    db.commit()
    current = timeline.get_entry(db, reader, scope, parent)
    assert current["withdrawn"] and current["revised"] and current["body"] is None
    reply_target = timeline.get_entry(db, reader, scope, reply)["reply_to"]
    assert reply_target["entry_id"] == str(parent)
    assert reply_target["actor_name"] == (editor.nickname or editor.username) and reply_target["revised"]
    assert reply_target["withdrawn"] and reply_target["body_preview"] is None
    assert not timeline.list_entries(db, reader, scope, keyword="original")["items"]
    assert not timeline.list_entries(db, reader, scope, keyword="current")["items"]
    newest = timeline.list_revisions(db, reader, scope, parent, limit=1)
    assert newest["items"][0]["reason"] == "resolved"
    assert newest["items"][0]["actor_name"] == (owner.nickname or owner.username)
    assert timeline.get_revision(db, reader, scope, parent, 2)["actor_name"] == (editor.nickname or editor.username)
    older = timeline.list_revisions(db, reader, scope, parent, cursor=newest["next_cursor"])
    assert [(row["version"], row["body"]) for row in older["items"]] == [(2, "current"), (1, "original")]


def test_scope_keyset_pages_ignore_newer_rows_and_resolve_equal_timestamps(db, world, scopes):
    scope, other, _ = scopes
    owner = world["admin"]
    ids = [UUID(timeline.append_entry(
        db, owner, scope, request_id=uuid4(), body=f"match {i}"
    )["entry_id"]) for i in range(3)]
    # Simulate imported equal timestamps and ensure UUID resolves ties.
    for entry in db.scalars(select(TimelineEntry)):
        entry.occurred_at = datetime(2026, 1, 1, tzinfo=UTC)
    db.commit()
    first = timeline.list_entries(db, owner, scope, limit=1, keyword="match")
    timeline.append_entry(db, owner, scope, request_id=uuid4(), body="match latest")
    db.commit()
    remaining = timeline.list_entries(db, owner, scope, cursor=first["next_cursor"], keyword="match")
    selected = first["items"] + remaining["items"]
    assert [UUID(row["id"]) for row in selected] == sorted(ids, reverse=True)
    assert remaining["next_cursor"] is None
    assert_code("invalid_request", lambda: timeline.list_entries(
        db, owner, other, cursor=first["next_cursor"], keyword="match"
    ))
    assert_code("invalid_request", lambda: timeline.list_entries(
        db, owner, scope, cursor=first["next_cursor"], keyword="latest"
    ))
    anchor = sorted(ids, reverse=True)[1]
    context = timeline.get_context(db, owner, scope, anchor, radius=1)
    assert context["anchor_id"] == str(anchor)
    assert [UUID(row["id"]) for row in context["items"]] == sorted(ids, reverse=True)
    body = "prefix " * 200 + "A literal _match%"
    result = timeline.append_entry(db, owner, scope, request_id=uuid4(), body=body)
    found = timeline.list_entries(db, owner, scope, keyword="_match%")["items"]
    assert [row["id"] for row in found] == [result["entry_id"]]
    assert "_match%" in found[0]["body_preview"]


def test_db_foreign_key_rejects_cross_requirement_reply(db, world, scopes):
    scope, other, _ = scopes
    db.connection().exec_driver_sql("PRAGMA foreign_keys = ON")
    receipt = timeline.append_entry(db, world["admin"], scope, request_id=uuid4(), body="original")
    db.add(TimelineEntry(
        project_id=other.project_id, requirement_code=other.identifier,
        kind="manual", latest_version=1, reply_to_id=UUID(receipt["entry_id"]),
        occurred_at=datetime.now(UTC), actor_id=world["admin"].id,
    ))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        db.flush()
    db.rollback()


def test_child_work_and_discussion_count_as_recent_activity(db, world, scopes):
    scope, other, _ = scopes
    editor = world["admin"]
    for ref in (scope, other):
        db.get(Requirement, (ref.project_id, ref.identifier)).updated_at = datetime.now(UTC) - timedelta(days=10)
    db.commit()
    def recent_codes():
        return [row["id"] for row in requirements.list_requirements(
            db, editor, scope.project_id, None, None, 20, updated_within_days=3)["items"]]
    assert recent_codes() == []
    tasks.create_task(db, editor, scope.project_id, "新任务", requirement_id=scope.identifier)
    assert recent_codes() == [scope.identifier]
    timeline.append_entry(db, editor, other, request_id=uuid4(), body="验收")
    db.commit()
    assert recent_codes() == [other.identifier, scope.identifier]
    system_events = timeline.list_entries(db, editor, scope, kind="system", keyword="创建任务")["items"]
    assert len(system_events) == 1 and system_events[0]["source_task"] == scope.identifier + "-T1"


def test_task_activity_stays_in_its_requirement(db, world, scopes, monkeypatch):
    scope, other, _ = scopes
    owner = world["admin"]
    task_code = scope.identifier + "-T1"
    db.add(Task(project_id=scope.project_id, code=task_code, requirement_id=scope.identifier,
                title="交接", status="backlog"))
    db.commit()
    requirements.set_requirement_status(db, owner, scope.identifier, "in_progress", project_id=scope.project_id)
    tasks.claim_task(db, owner, task_code, project_id=scope.project_id)
    assert_code("conflict", lambda: tasks.claim_task(db, owner, task_code, project_id=scope.project_id))
    tasks.set_task_status(db, owner, task_code, "in_progress", project_id=scope.project_id)
    tasks.set_task_status(db, owner, task_code, "done", project_id=scope.project_id)
    initial = timeline.list_entries(db, owner, scope)["items"]
    moved = timeline.list_entries(db, owner, other)["items"]
    assert {item["event_type"] for item in initial} == {
        "requirement.status_changed", "task.claimed", "task.status_changed",
    }
    assert len(initial) == 4
    assert any(item["source_task"] == task_code and item["event_data"] == {
        "before": "backlog", "after": "in_progress",
    } for item in initial)
    assert moved == []
    assert initial[0]["event_data"] == {"before": "in_progress", "after": "done"}

    def fail_event(*args, **kwargs):
        raise RuntimeError("timeline unavailable")

    monkeypatch.setattr(tasks, "record_system_event", fail_event)
    with pytest.raises(RuntimeError, match="timeline unavailable"):
        tasks.set_task_status(db, owner, task_code, "backlog", project_id=scope.project_id)
    db.rollback()
    assert db.get(Task, (scope.project_id, task_code)).status == "done"


def test_web_entries_use_scoped_receipts_and_public_errors(client, world, scopes):
    scope, _, _ = scopes
    login(client, "admin", "admin-pass-1")
    path = f"/api{scope.path}/timeline"
    data = {"request_id": str(uuid4()), "body": "from Web"}
    result = client.post(path, json=data)
    assert result.status_code == 201, result.text
    receipt = result.json()
    assert client.post(path, json=data).json() == receipt
    detail = client.get(f"{path}/{receipt['entry_id']}").json()
    assert detail["body"] == "from Web"
    error = client.post(path, json={"body": "missing request identity"})
    assert error.status_code == 400
    assert error.json()["code"] == "invalid_request"
