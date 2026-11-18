"""需求/任务 API 端到端(HTTP):错误四件套形状 + 完整闭环 + cursor 分页。"""

import uuid

from fastapi.testclient import TestClient

from app.tests.conftest import login


def test_requirement_crud_and_status_loop(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)

    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": "做登录"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    rid = resp.json()["id"]

    resp = client.get(f"/api/projects/{pid}/requirements")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["title"] == "做登录"
    assert resp.json()["next_cursor"] is None

    resp = client.patch(f"/api/requirements/{rid}", json={"description": "加个说明", "expected_version": 1})
    assert resp.status_code == 200
    assert resp.json()["description"] == "加个说明"

    resp = client.post(f"/api/requirements/{rid}/status", json={"status": "backlog"})
    assert resp.status_code == 200

    # 任务全链路:创建→认领→set_status 自由流转;任务状态不影响需求(自动流转已删除)
    resp = client.post(
        f"/api/projects/{pid}/tasks", json={"title": "实现登录页", "requirement_id": rid}
    )
    assert resp.status_code == 201
    tid = resp.json()["id"]
    assert resp.json()["status"] == "backlog"

    resp = client.post(f"/api/tasks/{tid}/claim")
    assert resp.status_code == 200
    assert resp.json()["assignee_id"] == str(world["admin"].id)

    resp = client.post(f"/api/tasks/{tid}/status", json={"status": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"
    # 任务开工不影响需求(仍待办)
    assert client.get(f"/api/requirements/{rid}").json()["status"] == "backlog"

    resp = client.post(f"/api/tasks/{tid}/status", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"
    # 任务完成后需求仍待办:需求状态全手动,需显式 set_status
    assert client.get(f"/api/requirements/{rid}").json()["status"] == "backlog"

    # 需求带未决任务也可直达 done(无任何前置校验)
    resp = client.post(f"/api/requirements/{rid}/status", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"

    # 非法目标态 → invalid_request;同态再转 → conflict
    resp = client.post(f"/api/tasks/{tid}/status", json={"status": "nonsense"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    resp = client.post(f"/api/tasks/{tid}/status", json={"status": "done"})
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"

    # 活动流记录整条链路(需求仅显式 set_status 记 activity)
    activity = client.get(f"/api/targets/requirement/{rid}/activity").json()["items"]
    actions = [a["action"] for a in activity]
    assert actions == ["create", "update", "status", "status"]
    task_activity = client.get(f"/api/targets/task/{tid}/activity").json()["items"]
    assert [a["action"] for a in task_activity] == [
        "create", "claim", "status", "status",
    ]

    # 评论 + 引用
    resp = client.post(f"/api/targets/requirement/{rid}/comments", json={"body": "评论一下"})
    assert resp.status_code == 201
    assert len(client.get(f"/api/targets/requirement/{rid}/comments").json()["items"]) == 1
    cid = resp.json()["id"]

    assert client.post(f"/api/targets/requirement/{rid}/references", json={}).status_code == 404
    current = client.get(f"/api/requirements/{rid}").json()
    body = f"[实现](/projects/{pid}/tasks/{tid})"
    assert client.patch(f"/api/requirements/{rid}", json={
        "expected_version": current["version"], "description": body,
    }).status_code == 200
    refs = client.get(f"/api/projects/{pid}/markdown/backlinks?target_kind=tasks&target_id={tid}").json()
    assert [r["id"] for r in refs["items"]] == [rid]
    assert client.delete(f"/api/comments/{cid}").status_code == 200

    # 需求软删:已有任务,需二次确认
    resp = client.post(f"/api/requirements/{rid}/delete", json={})
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"
    resp = client.post(f"/api/requirements/{rid}/delete", json={"confirm_task_count": 1})
    assert resp.status_code == 200
    assert client.get(f"/api/requirements/{rid}").status_code == 404
    assert client.post(f"/api/requirements/{rid}/restore").status_code == 200


def test_error_four_piece_shape(client: TestClient, world: dict, db):
    from app.security import hash_password

    world["member"].password_hash = hash_password("bob-pass-1")
    db.commit()
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    resp = client.get(f"/api/projects/{pid}/requirements")
    rid = resp.json()["items"][0]["id"] if resp.json()["items"] else None
    if rid is None:
        rid = str(uuid.uuid4())
        client.post(f"/api/projects/{pid}/requirements", json={"title": "x"})
        resp = client.get(f"/api/projects/{pid}/requirements")
        rid = resp.json()["items"][0]["id"]

    # viewer 写 → permission_denied
    login(client, "bob", "bob-pass-1")
    resp = client.patch(f"/api/requirements/{rid}", json={"title": "hack"})
    assert resp.status_code == 403
    assert resp.json() == {"code": "permission_denied", "message": resp.json()["message"]}

    # 不存在 → not_found(非成员视角 404,不泄露存在性)
    resp = client.get("/api/requirements/REQ-999")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    # 非法流转 → conflict
    login(client, "admin", "admin-pass-1")
    resp = client.post(f"/api/requirements/{rid}/cancel")
    assert resp.status_code == 200
    resp = client.post(f"/api/requirements/{rid}/cancel")
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"

    # 参数缺失 → invalid_request(状态机校验层)
    resp = client.post(f"/api/projects/{pid}/requirements", json={"title": " "})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"


def test_cursor_pagination(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    for i in range(25):
        client.post(f"/api/projects/{pid}/requirements", json={"title": f"需求 {i}"})

    page1 = client.get(f"/api/projects/{pid}/requirements?limit=10").json()
    assert len(page1["items"]) == 10
    assert page1["next_cursor"] is not None
    page2 = client.get(
        f"/api/projects/{pid}/requirements?limit=10&cursor={page1['next_cursor']}"
    ).json()
    assert len(page2["items"]) == 10
    page3 = client.get(
        f"/api/projects/{pid}/requirements?limit=10&cursor={page2['next_cursor']}"
    ).json()
    assert len(page3["items"]) == 5
    assert page3["next_cursor"] is None
    ids = {r["id"] for r in page1["items"] + page2["items"] + page3["items"]}
    assert len(ids) == 25

    # 跨筛选条件复用游标 → invalid_request
    resp = client.get(
        f"/api/projects/{pid}/requirements?status=backlog&cursor={page1['next_cursor']}"
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 损坏游标 → invalid_request
    resp = client.get(f"/api/projects/{pid}/requirements?cursor=not-a-cursor")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
