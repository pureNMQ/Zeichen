import pytest

from app.errors import AppError
from app.services import requirements, tasks
from app.services.requirement_board import set_blockers
from app.v2.resource_refs import ResourceKind, ResourceRef
from app.v2.timeline import record_manual_entry
from .conftest import login


def test_requirement_dependencies_follow_status_and_reject_cycles(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    base = f"/api/projects/{pid}/requirements"
    a, b, c = [client.post(base, json={"title": title}).json()["id"] for title in ["名册", "邀请", "入组"]]

    def edges(code, values):
        return client.patch(f"/api/requirements/{code}?project_id={pid}", json={"blocked_by": values})

    assert edges(b, [a]).json()["blocked"]
    stale = client.patch(f"/api/requirements/{b}?project_id={pid}", json={"blocked_by": [], "expected_blocked_by": []})
    assert stale.status_code == 409
    assert edges(c, [a, b]).json()["blocked"]
    assert edges(a, [c]).status_code == 409
    assert edges(a, [a]).status_code == 400
    assert edges(a, ["REQ-9999"]).status_code == 404
    assert [item["id"] for item in client.get(f"{base}/{a}").json()["blocks"]] == [b, c]
    for status, expected in [("done", False), ("in_progress", True), ("cancelled", True)]:
        assert client.post(f"{base}/{a}/status", json={"status": status}).status_code == 200
        assert client.get(f"{base}/{b}").json()["blocked"] is expected
        assert client.get(f"{base}/{c}").json()["blocked"]
    assert edges(b, []).json()["blocked_by"] == []


def test_participation_survives_reassignment_and_includes_timeline(db, world):
    pid = world["project"].id
    admin, agent, owner = (world[key] for key in ["admin", "agent", "agent_owner"])
    r = requirements.create_requirement(db, admin, pid, "协作")
    other = requirements.create_requirement(db, admin, pid, "其他")
    task = tasks.create_task(db, admin, pid, "核对名册", requirement_id=r.code)
    tasks.assign_task(db, agent, task.code, owner.id, project_id=pid)
    tasks.unassign_task(db, admin, task.code, project_id=pid)
    data = requirements._requirement_dict(db, r)
    assert {p["id"] for p in data["participants"]} == {str(admin.id), str(agent.id), str(owner.id)}
    assert requirements.list_requirements(db, owner, pid, None, None, 20, participated_by_me=True)["items"][0]["id"] == r.code
    record_manual_entry(db, agent, ResourceRef(pid, ResourceKind.REQUIREMENT, other.code), body="测试说明")
    db.commit()
    rows = requirements.list_requirements(db, owner, pid, None, None, 20, participated_by_me=True)["items"]
    assert {row["id"] for row in rows} == {r.code, other.code}
    with pytest.raises(AppError):
        set_blockers(db, world["member"], r.code, pid, [other.code])
