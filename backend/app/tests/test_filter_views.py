"""个人筛选视图持久化(project_filter_view)API 测试。

契约要点(红阶段,生产未实现):
- 仅本人可见可改:他人视图一律 not_found(404),不泄露存在性
- criteria 白名单键 + 对应实体状态集校验;未知键/非法值 → invalid_request
- 同名(用户×项目×entity_type)重复 → conflict;物理删除后可重建
- 列表/创建:项目成员(viewer 及以上)可访问;非项目成员 → not_found(不泄露项目存在性)
- 响应形状 8 键:{id, project_id, user_id, entity_type, name, criteria, created_at, updated_at}
"""

import uuid

from fastapi.testclient import TestClient

from app.models import ProjectMember
from app.security import hash_password

from .conftest import login, make_user

VIEW_KEYS = {
    "id",
    "project_id",
    "user_id",
    "entity_type",
    "name",
    "criteria",
    "created_at",
    "updated_at",
}


def _assert_view_shape(body: dict) -> str:
    """契约响应形状:恰好 8 键;返回视图 id。"""
    assert set(body.keys()) == VIEW_KEYS
    return body["id"]


def _create_view(client: TestClient, pid: str, entity_type: str = "requirement", name: str = "视图", criteria: dict | None = None) -> dict:
    resp = client.post(
        f"/api/projects/{pid}/filter-views",
        json={"entity_type": entity_type, "name": name, "criteria": criteria or {}},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_filter_view_crud_loop(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)

    # 创建 requirement 视图 → 201,形状契约
    resp = client.post(
        f"/api/projects/{pid}/filter-views",
        json={
            "entity_type": "requirement",
            "name": "全部需求",
            "criteria": {"statuses": ["pending", "backlog"], "view_mode": "board"},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    vid = _assert_view_shape(body)
    assert body["project_id"] == pid
    assert body["user_id"] == str(world["admin"].id)
    assert body["entity_type"] == "requirement"
    assert body["name"] == "全部需求"
    assert body["criteria"] == {"statuses": ["pending", "backlog"], "view_mode": "board"}

    # 列表按 entity_type 过滤
    resp = client.get(f"/api/projects/{pid}/filter-views?entity_type=requirement")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["items"]) == 1
    _assert_view_shape(resp.json()["items"][0])
    assert resp.json()["items"][0]["id"] == vid

    resp = client.get(f"/api/projects/{pid}/filter-views?entity_type=task")
    assert resp.status_code == 200, resp.text
    assert resp.json()["items"] == []

    # 详情
    resp = client.get(f"/api/filter-views/{vid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "全部需求"

    # 改名
    resp = client.patch(f"/api/filter-views/{vid}", json={"name": "进行中的需求"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "进行中的需求"

    # 改 criteria
    resp = client.patch(
        f"/api/filter-views/{vid}",
        json={"criteria": {"statuses": ["in_progress", "done"], "updated_within_days": 7}},
    )
    assert resp.status_code == 200
    assert resp.json()["criteria"] == {"statuses": ["in_progress", "done"], "updated_within_days": 7}

    # 删除 → {ok: True};物理删除后详情 404
    resp = client.delete(f"/api/filter-views/{vid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    resp = client.get(f"/api/filter-views/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_task_view_full_criteria_roundtrip(client: TestClient, world: dict):
    """task 视图可携带全部 criteria 键(含 assignee_id),详情原样返回。"""
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    criteria = {
        "statuses": ["backlog", "in_progress", "done"],
        "updated_within_days": 30,
        "keyword": "搜索",
        "assignee_id": str(world["member"].id),
        "view_mode": "list",
    }
    body = _create_view(client, pid, entity_type="task", name="我的任务", criteria=criteria)
    assert body["criteria"] == criteria
    resp = client.get(f"/api/filter-views/{body['id']}")
    assert resp.status_code == 200
    assert resp.json()["criteria"] == criteria


def test_filter_views_are_private_per_user(client: TestClient, db, world: dict):
    """A 建的视图,B(同项目成员)列表看不到、详情/PATCH/DELETE 404。"""
    carol = make_user(db, "carol", with_password="carol-pass-1")
    db.add(ProjectMember(project_id=world["project"].id, user_id=carol.id, role="viewer"))
    db.commit()

    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    vid = _create_view(client, pid, name="私有视图")["id"]

    # B 同项目:列表看不到 A 的视图
    client.post("/api/auth/logout")
    login(client, "carol", "carol-pass-1")
    resp = client.get(f"/api/projects/{pid}/filter-views?entity_type=requirement")
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    # 详情 / PATCH / DELETE → not_found(不泄露他人视图存在性)
    resp = client.get(f"/api/filter-views/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    resp = client.patch(f"/api/filter-views/{vid}", json={"name": "hack"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    resp = client.delete(f"/api/filter-views/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    # B 可建自己的同名视图(唯一约束是 用户×项目×entity_type×name)
    resp = client.post(
        f"/api/projects/{pid}/filter-views",
        json={"entity_type": "requirement", "name": "私有视图", "criteria": {}},
    )
    assert resp.status_code == 201
    assert resp.json()["user_id"] == str(carol.id)

    # A 的视图仍在
    client.post("/api/auth/logout")
    login(client, "admin", "admin-pass-1")
    resp = client.get(f"/api/filter-views/{vid}")
    assert resp.status_code == 200


def test_filter_view_validation(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    url = f"/api/projects/{pid}/filter-views"

    def create(**overrides):
        body = {"entity_type": "requirement", "name": "校验", "criteria": {}}
        body.update(overrides)
        return client.post(url, json=body)

    # 非法 entity_type / 缺失 entity_type
    resp = create(entity_type="document")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    resp = client.post(url, json={"name": "校验", "criteria": {}})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 列表:entity_type 必填且合法
    resp = client.get(f"/api/projects/{pid}/filter-views?entity_type=document")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    resp = client.get(f"/api/projects/{pid}/filter-views")
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # 未知 criteria 键
    resp = create(criteria={"bogus": 1})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"

    # statuses 含非法状态
    resp = create(criteria={"statuses": ["nonsense"]})
    assert resp.status_code == 400
    # verifying 现为需求合法状态(ADR 0003 六态)
    resp = create(name="验收视图", criteria={"statuses": ["verifying"]})
    assert resp.status_code == 201
    # task 视图出现 requirement 独有状态(pending/verifying 均非法)
    resp = create(entity_type="task", criteria={"statuses": ["pending"]})
    assert resp.status_code == 400
    resp = create(entity_type="task", criteria={"statuses": ["verifying"]})
    assert resp.status_code == 400
    # statuses 不是列表
    resp = create(criteria={"statuses": "backlog"})
    assert resp.status_code == 400

    # updated_within_days = 0 / 负数
    resp = create(criteria={"updated_within_days": 0})
    assert resp.status_code == 400
    resp = create(criteria={"updated_within_days": -3})
    assert resp.status_code == 400

    # keyword > 100
    resp = create(criteria={"keyword": "x" * 101})
    assert resp.status_code == 400

    # view_mode 非法
    resp = create(criteria={"view_mode": "calendar"})
    assert resp.status_code == 400

    # requirement 视图带 assignee_id → invalid_request
    resp = create(criteria={"assignee_id": str(uuid.uuid4())})
    assert resp.status_code == 400
    # task 视图 assignee_id 非 UUID
    resp = create(entity_type="task", criteria={"assignee_id": "not-a-uuid"})
    assert resp.status_code == 400

    # name > 50
    resp = create(name="n" * 51)
    assert resp.status_code == 400

    # 合法边界:keyword 恰好 100、updated_within_days=1、view_mode=board
    resp = create(criteria={"keyword": "x" * 100, "updated_within_days": 1, "view_mode": "board"})
    assert resp.status_code == 201


def test_filter_view_duplicate_name_conflict(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    payload = {"entity_type": "requirement", "name": "同名视图", "criteria": {"statuses": ["backlog"]}}
    assert client.post(f"/api/projects/{pid}/filter-views", json=payload).status_code == 201

    # 同用户×项目×entity_type×名称 → conflict
    resp = client.post(f"/api/projects/{pid}/filter-views", json=payload)
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict"

    # 同名但不同 entity_type → 允许
    resp = client.post(
        f"/api/projects/{pid}/filter-views",
        json={"entity_type": "task", "name": "同名视图", "criteria": {}},
    )
    assert resp.status_code == 201


def test_filter_view_permissions(client: TestClient, db, world: dict):
    """非项目成员列表/创建 → not_found(不泄露项目存在性);viewer 可建自己的视图。"""
    world["member"].password_hash = hash_password("bob-pass-1")
    make_user(db, "dave", with_password="dave-pass-1")  # 工作区成员,非项目成员
    db.commit()

    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    vid = _create_view(client, pid, name="admin 的视图")["id"]

    # 非项目成员:列表 / 创建 → not_found(平台惯例:get_accessible_project 不泄露项目存在性)
    client.post("/api/auth/logout")
    login(client, "dave", "dave-pass-1")
    resp = client.get(f"/api/projects/{pid}/filter-views?entity_type=requirement")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    resp = client.post(
        f"/api/projects/{pid}/filter-views",
        json={"entity_type": "requirement", "name": "越权", "criteria": {}},
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    # 非成员看他人视图 详情/PATCH/DELETE → not_found(不泄露存在性)
    resp = client.get(f"/api/filter-views/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    resp = client.patch(f"/api/filter-views/{vid}", json={"name": "hack"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    resp = client.delete(f"/api/filter-views/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"

    # viewer(bob,项目成员)可创建自己的视图并列出(仅本人)
    client.post("/api/auth/logout")
    login(client, "bob", "bob-pass-1")
    resp = client.post(
        f"/api/projects/{pid}/filter-views",
        json={"entity_type": "requirement", "name": "bob 的视图", "criteria": {}},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user_id"] == str(world["member"].id)
    resp = client.get(f"/api/projects/{pid}/filter-views?entity_type=requirement")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "bob 的视图"
    assert items[0]["user_id"] == str(world["member"].id)


def test_filter_view_physical_delete_semantics(client: TestClient, world: dict):
    """物理删除:详情 404、列表不含、同名可重建(与软删需求不同)。"""
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    payload = {"entity_type": "task", "name": "可重建视图", "criteria": {"statuses": ["backlog"]}}
    resp = client.post(f"/api/projects/{pid}/filter-views", json=payload)
    assert resp.status_code == 201
    vid = resp.json()["id"]

    resp = client.delete(f"/api/filter-views/{vid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    resp = client.get(f"/api/filter-views/{vid}")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
    items = client.get(f"/api/projects/{pid}/filter-views?entity_type=task").json()["items"]
    assert all(item["id"] != vid for item in items)

    # 物理删除后同名可再次创建
    resp = client.post(f"/api/projects/{pid}/filter-views", json=payload)
    assert resp.status_code == 201
    assert resp.json()["id"] != vid
