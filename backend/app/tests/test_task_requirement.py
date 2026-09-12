"""任务↔需求关联(ADR 0003 任务收归需求):任务必挂需求,PATCH 只可改指向不可解除。

- 创建必须指定同项目已确认需求;缺失/待确认/他项目/不存在 → invalid_request / not_found
- PATCH requirement_id 可改指向同项目其他需求;显式 null → invalid_request
- 权限与改状态同规则:已指派仅本人/工作区 admin/项目 owner,未指派任意编辑权
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Project, ProjectMember
from app.security import hash_password
from app.tests.conftest import login, make_user


def _req(client: TestClient, pid: str, title: str) -> dict:
    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": title})
    assert resp.status_code == 201, resp.text
    requirement = resp.json()
    resp = client.post(
        f"/api/requirements/{requirement['id']}/status", json={"status": "backlog"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _task(client: TestClient, pid: str, rid: str, title="任务") -> dict:
    resp = client.post(f"/api/projects/{pid}/tasks", json={"title": title, "requirement_id": rid})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_requires_same_project_requirement(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r = _req(client, pid, "需求")

    # 缺失 → invalid_request
    resp = client.post(f"/api/projects/{pid}/tasks", json={"title": "无主任务"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 不存在 → not_found
    resp = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "幽灵任务", "requirement_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    # 正常创建
    resp = client.post(f"/api/projects/{pid}/tasks", json={"title": "任务", "requirement_id": r["id"]})
    assert resp.status_code == 201
    assert resp.json()["requirement_id"] == r["id"]


def test_change_requirement_but_not_clear(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r1 = _req(client, pid, "需求一")
    r2 = _req(client, pid, "需求二")
    t = _task(client, pid, r1["id"])
    tid = t["id"]

    # 更换 → OK
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r2["id"]

    # 显式 null 解除 → invalid_request
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": None})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    assert client.get(f"/api/tasks/{tid}").json()["requirement_id"] == r2["id"]

    # 未传字段 = 不变
    resp = client.patch(f"/api/tasks/{tid}", json={"title": "改名"})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r2["id"]

    # 活动流记录关联变更(不再有「解除需求关联」)
    activity = client.get(f"/api/targets/task/{tid}/activity").json()["items"]
    summaries = [a["summary"] for a in activity]
    assert "关联需求" in summaries
    assert "解除需求关联" not in summaries


def test_cross_project_and_deleted_requirement_rejected(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    other = Project(team_id=world["team"].id, name="另一个项目")
    db.add(other)
    db.commit()
    r_other = _req(client, str(other.id), "他项目需求")
    r = _req(client, pid, "本需求")
    t = _task(client, pid, r["id"])

    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r_other["id"]})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    assert client.get(f"/api/tasks/{t['id']}").json()["requirement_id"] == r["id"]

    r_dead = _req(client, pid, "将被删的需求")
    client.post(f"/api/requirements/{r_dead['id']}/delete", json={})
    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r_dead["id"]})
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
    r1 = _req(client, pid, "需求一")
    r2 = _req(client, pid, "需求二")

    # 未指派:viewer → 403,editor → 通过(任务以 admin 身份预建,bob/carol 只测 PATCH)
    t = _task(client, pid, r1["id"])
    login(client, "bob", "bob-pass-1")
    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "permission_denied"
    login(client, "carol", "carol-pass-1")
    resp = client.patch(f"/api/tasks/{t['id']}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r2["id"]

    # 已指派给 agent:非本人 editor carol → 403;工作区 admin → 通过
    login(client, "admin", "admin-pass-1")
    t3 = client.post(
        f"/api/projects/{pid}/tasks",
        json={
            "title": "已指派任务",
            "requirement_id": r1["id"],
            "assignee_id": str(world["agent"].id),
        },
    ).json()
    login(client, "carol", "carol-pass-1")
    resp = client.patch(f"/api/tasks/{t3['id']}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 403
    assert resp.json()["code"] == "permission_denied"
    login(client, "admin", "admin-pass-1")
    resp = client.patch(f"/api/tasks/{t3['id']}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r2["id"]

    # 本人(agent,经服务层直接调用)可改指向,但置空被拒
    from app.services import tasks as task_svc

    tid = uuid.UUID(t3["id"])
    got = task_svc.update_task(db, world["agent"], tid, requirement_id=r1["id"])
    assert str(got.requirement_id) == r1["id"]
    with pytest.raises(AppError) as e:
        task_svc.update_task(db, world["agent"], tid, requirement_id=None)
    assert e.value.code == "invalid_request"
