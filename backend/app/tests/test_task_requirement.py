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
    # 项目内确认端点:避免跨项目同码时的无上下文消歧(ADR 0002)
    resp = client.post(
        f"/api/projects/{pid}/requirements/{requirement['id']}/status",
        json={"status": "backlog"},
    )
    assert resp.status_code == 200, resp.text
    return requirement


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

    # 旧 UUID/非法格式 → invalid_request(ADR 0002 无 UUID 兼容)
    resp = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "幽灵任务", "requirement_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    # 合法格式但不存在 → not_found
    resp = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "幽灵任务", "requirement_id": "REQ-999"},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    # 正常创建
    resp = client.post(f"/api/projects/{pid}/tasks", json={"title": "任务", "requirement_id": r["id"]})
    assert resp.status_code == 201
    assert resp.json()["requirement_id"] == r["id"]


def test_tasks_numbered_per_requirement_and_cannot_be_moved(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    first = _req(client, pid, "一")["id"]
    second = _req(client, pid, "二")["id"]
    t1 = _task(client, pid, first)
    t2 = _task(client, pid, second)
    assert t1["id"] == first + "-T1"
    assert t2["id"] == second + "-T1"
    assert client.patch(f"/api/tasks/{t1['id']}", json={"requirement_id": second}).status_code == 422
    assert client.get(f"/api/tasks/{t1['id']}").json()["requirement_id"] == first
    client.post(f"/api/tasks/{t1['id']}/delete")
    assert _task(client, pid, first)["id"] == first + "-T2"
