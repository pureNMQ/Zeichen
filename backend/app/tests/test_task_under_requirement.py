"""任务收归需求(ADR 0003):REST 面必挂需求、任务四态/需求六态、task 评论拒绝。

- 创建任务(REST)requirement_id 必填;缺失 → invalid_request;他项目 → invalid_request
- update 禁止置空解除关联;可改指向同项目其他需求
- 任务状态无 verifying(四态);需求状态新增 verifying(六态)
- comment.create/list 对 task 目标 → invalid_request;需求/文档评论不受影响
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.tests.conftest import login


def _req(client: TestClient, pid: str, title: str, status: str = "backlog") -> dict:
    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": title})
    assert resp.status_code == 201, resp.text
    rid = resp.json()["id"]
    if status != "pending":
        resp = client.post(f"/api/requirements/{rid}/status", json={"status": status})
        assert resp.status_code == 200, resp.text
    return {"id": rid, **resp.json()} if status == "pending" else {"id": rid}


def test_create_task_requires_requirement(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    resp = client.post(f"/api/projects/{pid}/tasks", json={"title": "无主任务"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


def test_create_task_cross_project_requirement_rejected(client: TestClient, world: dict, db: Session):
    from app.models import Project

    login(client, "admin", "admin-pass-1")
    other = Project(team_id=world["team"].id, name="另一个项目")
    db.add(other)
    db.commit()
    r_other = _req(client, str(other.id), "他项目需求")

    pid = str(world["project"].id)
    # ADR 0002:需求短码按任务所在项目寻址;他项目同码在本项目不存在 → not_found
    resp = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "跨项目任务", "requirement_id": r_other["id"]},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_create_task_pending_requirement_rejected(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r = _req(client, pid, "待确认需求", status="pending")
    resp = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "过早拆解", "requirement_id": r["id"]}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


def test_update_cannot_clear_requirement(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r1 = _req(client, pid, "需求一")
    r2 = _req(client, pid, "需求二")
    resp = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "任务", "requirement_id": r1["id"]}
    )
    assert resp.status_code == 201
    tid = resp.json()["id"]
    assert resp.json()["requirement_id"] == r1["id"]

    # 置空解除 → invalid_request
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": None})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 改指向同项目其他需求 → OK
    resp = client.patch(f"/api/tasks/{tid}", json={"requirement_id": r2["id"]})
    assert resp.status_code == 200
    assert resp.json()["requirement_id"] == r2["id"]


def test_task_four_states_no_verifying(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r = _req(client, pid, "需求")
    resp = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "四态任务", "requirement_id": r["id"]}
    )
    tid = resp.json()["id"]

    # verifying 已非法(四态)
    resp = client.post(f"/api/tasks/{tid}/status", json={"status": "verifying"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 其余状态自由流转(含同态 conflict 规则不变)
    for status in ("in_progress", "done", "backlog", "cancelled"):
        resp = client.post(f"/api/tasks/{tid}/status", json={"status": status})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == status


def test_requirement_six_states_with_verifying(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r = _req(client, pid, "验收语义需求")
    resp = client.post(f"/api/requirements/{r['id']}/status", json={"status": "verifying"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "verifying"
    # 同态再转 conflict 规则不变
    resp = client.post(f"/api/requirements/{r['id']}/status", json={"status": "verifying"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"


def test_task_comments_rejected(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r = _req(client, pid, "需求")
    resp = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "任务", "requirement_id": r["id"]}
    )
    tid = resp.json()["id"]

    resp = client.post(f"/api/targets/task/{tid}/comments", json={"body": "任务评论"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    resp = client.get(f"/api/targets/task/{tid}/comments")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 需求评论不受影响
    resp = client.post(f"/api/targets/requirement/{r['id']}/comments", json={"body": "需求评论"})
    assert resp.status_code == 201
    resp = client.get(f"/api/targets/requirement/{r['id']}/comments")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
