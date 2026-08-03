"""任务↔需求关联(ticket 10):PATCH /tasks/{id} requirement_id 设置/更换/解除/跨项目拒绝/权限。

- 未传字段 = 不变;传 null = 解除关联
- 需求须存在、未删除、与任务同项目(跨项目 → invalid_request)
- 权限与改状态同规则:已指派仅本人/工作区 admin/项目 owner,未指派任意编辑权
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember
from app.security import hash_password
from app.tests.conftest import login, make_user


def _req(client: TestClient, pid: str, title: str) -> dict:
    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _task(client: TestClient, pid: str, title="任务") -> dict:
    resp = client.post(f"/api/projects/{pid}/tasks", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_set_change_clear_requirement(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r1 = _req(client, pid, "需求一")
    r2 = _req(client, pid, "需求二")
    t = _task(client, pid)
    tid = t["id"]
    assert t["requirement_id"] is None

    # 设置
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": r1["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r1["id"]

    # 更换
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r2["id"]

    # 解除 = 显式 null
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": None})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] is None

    # 未传字段 = 不变
    client.patch(f"/api/tasks/{tid}", json={"requirement_id": r1["id"]})
    resp = client.patch(f"/api/tasks/{tid}", json={"title": "改名"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "改名"
    assert resp.json()["requirement_id"] == r1["id"]

    # 活动流记录关联/解除
    activity = client.get(f"/api/targets/task/{tid}/activity").json()["items"]
    actions = [a["action"] for a in activity]
    assert actions == ["create", "update", "update", "update", "update", "update"]
    assert "关联需求" in [a["summary"] for a in activity]
    assert "解除需求关联" in [a["summary"] for a in activity]


def test_cross_project_requirement_rejected(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    other = Project(team_id=world["team"].id, name="另一个项目")
    db.add(other)
    db.commit()
    r_other = _req(client, str(other.id), "他项目需求")
    t = _task(client, pid)

    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r_other["id"]})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    # 任务未挂上
    assert client.get(f"/api/tasks/{t['id']}").json()["requirement_id"] is None


def test_missing_and_deleted_requirement_rejected(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    t = _task(client, pid)

    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": str(uuid.uuid4())})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    r = _req(client, pid, "将被删的需求")
    client.post(f"/api/requirements/{r['id']}/delete", json={})
    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r["id"]})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_requirement_link_permissions(client: TestClient, world: dict, db: Session):
    """viewer 禁改;未指派任意编辑权;已指派仅本人/工作区 admin/项目 owner。"""
    world["member"].password_hash = hash_password("bob-pass-1")
    carol = make_user(db, "carol", role="member")
    carol.password_hash = hash_password("carol-pass-1")
    project = world["project"]
    db.add(ProjectMember(project_id=project.id, user_id=carol.id, role="editor"))
    db.commit()
    pid = str(project.id)

    login(client, "admin", "admin-pass-1")
    r = _req(client, pid, "需求")

    # 未指派:viewer → 403,editor → 通过(任务以 admin 身份预建,bob/carol 只测 PATCH)
    login(client, "admin", "admin-pass-1")
    t = _task(client, pid)
    login(client, "bob", "bob-pass-1")
    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r["id"]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "permission_denied"
    login(client, "carol", "carol-pass-1")
    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r["id"]

    # 已指派给 agent:非本人 editor carol → 403;工作区 admin → 通过
    login(client, "admin", "admin-pass-1")
    t3 = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "已指派任务", "assignee_id": str(world["agent"].id)},
    ).json()
    login(client, "carol", "carol-pass-1")
    resp = client.patch(f"/api/tasks/{t3['id']}", json={"requirement_id": r["id"]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "permission_denied"
    login(client, "admin", "admin-pass-1")
    resp = client.patch(f"/api/tasks/{t3['id']}", json={"requirement_id": r["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r["id"]

    # 本人(agent,经服务层直接调用)可解除已指派任务的关联
    from app.services import tasks as task_svc

    tid = uuid.UUID(t3["id"])
    got = task_svc.update_task(db, world["agent"], tid, requirement_id=None)
    assert got.requirement_id is None
