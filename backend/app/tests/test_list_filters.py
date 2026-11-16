"""T1 需求/任务列表筛选与排序(变更契约)。

- GET /api/projects/{id}/requirements 与 /tasks 新增查询参数:
  * status 可多值(重复参数形式 ?status=a&status=b,单值兼容)
  * updated_within_days 正整数(≥1),按 updated_at 距今天数过滤;<1 或非法 → invalid_request
  * keyword 标题或描述包含(大小写不敏感,ilike);tasks 另有既有 assignee_id
- 筛选在 offset/limit 分页前执行;cursor 条件哈希纳入全部筛选维度(status 列表排序后入哈希)
- 默认排序改为 updated_at 倒序 + id 倒序稳定次序(ORDER BY updated_at DESC, id DESC)

服务层新签名约定(实现并行进行,测试以此为准):
  list_requirements(db, user, project_id, status, cursor, limit, updated_within_days=None, keyword=None)
  list_tasks(db, user, project_id, requirement_id, assignee_id, status, cursor, limit,
             updated_within_days=None, keyword=None)
status 为多值 list[str] | None。
构造旧数据:直接改 DB 行的 updated_at 回拨,验证被时间窗口排除。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.errors import AppError
from app.models import Requirement, Task
from app.services import requirements as req_svc
from app.services import tasks as task_svc
from app.tests.conftest import login


def _ids(page: dict) -> set:
    return {i["id"] for i in page["items"]}


def _backdate(db: Session, model, entity_id, days: int) -> None:
    """把实体 updated_at 回拨 days 天(直接改 DB 行;短码实体按 code 定位)。"""
    row = db.scalar(select(model).where(model.code == entity_id).limit(1))
    assert row is not None
    row.updated_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()


def _mk_req(client: TestClient, pid: str, title: str, description=None, status=None) -> dict:
    resp = client.post(
        f"/api/projects/{pid}/requirements", json={"title": title, "description": description}
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()
    if status is not None:
        resp = client.post(f"/api/requirements/{item['id']}/status", json={"status": status})
        assert resp.status_code == 200, resp.text
    return item


def _mk_task(client: TestClient, pid: str, title: str, description=None, status=None) -> dict:
    rid = client.post(f"/api/projects/{pid}/requirements", json={"title": f"挂载:{title}"}).json()["id"]
    client.post(f"/api/requirements/{rid}/status", json={"status": "backlog"})
    resp = client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": title, "description": description, "requirement_id": rid},
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()
    if status is not None:
        resp = client.post(f"/api/tasks/{item['id']}/status", json={"status": status})
        assert resp.status_code == 200, resp.text
    return item


# ---------------------------------------------------------------------------
# 需求列表(HTTP)
# ---------------------------------------------------------------------------


def test_requirement_multi_status_filter(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    _mk_req(client, pid, "待确认需求")  # 默认即 pending,无需显式 set
    backlog = _mk_req(client, pid, "待办需求", status="backlog")
    doing = _mk_req(client, pid, "进行中需求", status="in_progress")
    _mk_req(client, pid, "已完成需求", status="done")

    # 重复参数多值:两个状态各返回对应项
    page = client.get(
        f"/api/projects/{pid}/requirements",
        params=[("status", "backlog"), ("status", "in_progress")],
    ).json()
    assert _ids(page) == {backlog["id"], doing["id"]}
    # 单值兼容
    page = client.get(f"/api/projects/{pid}/requirements", params={"status": "backlog"}).json()
    assert _ids(page) == {backlog["id"]}
    # 空结果
    page = client.get(f"/api/projects/{pid}/requirements", params={"status": "cancelled"}).json()
    assert page["items"] == []


def test_requirement_updated_within_days_window(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    fresh = _mk_req(client, pid, "新需求")
    old = _mk_req(client, pid, "旧需求")
    _backdate(db, Requirement, old["id"], 5)  # 回拨 5 天

    page = client.get(
        f"/api/projects/{pid}/requirements", params={"updated_within_days": 3}
    ).json()
    assert _ids(page) == {fresh["id"]}  # 旧数据被排除
    page = client.get(
        f"/api/projects/{pid}/requirements", params={"updated_within_days": 30}
    ).json()
    assert _ids(page) == {fresh["id"], old["id"]}  # 大窗口包含


def test_requirement_keyword_filter(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    _mk_req(client, pid, "Login Page", description="form validation")
    _mk_req(client, pid, "Payment Gateway", description="wechat pay")

    page = client.get(f"/api/projects/{pid}/requirements", params={"keyword": "login"}).json()
    assert len(page["items"]) == 1 and page["items"][0]["title"] == "Login Page"
    # 大小写不敏感
    page = client.get(f"/api/projects/{pid}/requirements", params={"keyword": "LOGIN"}).json()
    assert len(page["items"]) == 1 and page["items"][0]["title"] == "Login Page"
    # 描述命中
    page = client.get(f"/api/projects/{pid}/requirements", params={"keyword": "wechat"}).json()
    assert len(page["items"]) == 1 and page["items"][0]["title"] == "Payment Gateway"
    # 无命中
    page = client.get(f"/api/projects/{pid}/requirements", params={"keyword": "zzz-nope"}).json()
    assert page["items"] == []


def test_requirement_combined_filters(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    r1 = _mk_req(client, pid, "登录改造", status="backlog")
    r2 = _mk_req(client, pid, "支付改造", status="backlog")
    r3 = _mk_req(client, pid, "登录后台", status="in_progress")
    _backdate(db, Requirement, r3["id"], 5)

    # status + keyword
    page = client.get(
        f"/api/projects/{pid}/requirements", params={"status": "backlog", "keyword": "登录"}
    ).json()
    assert _ids(page) == {r1["id"]}
    # status + keyword + 时间窗口:回拨的 in_progress 被排除
    page = client.get(
        f"/api/projects/{pid}/requirements",
        params={"status": "in_progress", "keyword": "登录", "updated_within_days": 3},
    ).json()
    assert page["items"] == []
    # 去掉时间窗口则命中
    page = client.get(
        f"/api/projects/{pid}/requirements", params={"status": "in_progress", "keyword": "登录"}
    ).json()
    assert _ids(page) == {r3["id"]}
    # status + 时间窗口
    page = client.get(
        f"/api/projects/{pid}/requirements",
        params={"status": "backlog", "updated_within_days": 3},
    ).json()
    assert _ids(page) == {r1["id"], r2["id"]}


def test_updated_within_days_invalid_http(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    for bad in (0, -1, "abc"):
        resp = client.get(
            f"/api/projects/{pid}/requirements", params={"updated_within_days": bad}
        )
        assert resp.status_code == 400, (bad, resp.status_code, resp.text)
        assert resp.json()["code"] == "invalid_request"


def test_requirement_order_updated_at_desc_then_id_desc(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    a = _mk_req(client, pid, "旧需求")
    b = _mk_req(client, pid, "新需求一")
    c = _mk_req(client, pid, "新需求二")
    now = datetime.now(timezone.utc)
    db.scalar(select(Requirement).where(Requirement.code == a["id"]).limit(1)).updated_at = now - timedelta(hours=2)
    db.scalar(select(Requirement).where(Requirement.code == b["id"]).limit(1)).updated_at = now - timedelta(hours=1)
    db.scalar(select(Requirement).where(Requirement.code == c["id"]).limit(1)).updated_at = now - timedelta(hours=1)  # 与 b 相同 → id 倒序决胜
    db.commit()

    page = client.get(f"/api/projects/{pid}/requirements").json()
    assert len(page["items"]) == 3
    titles = [i["title"] for i in page["items"]]
    assert titles[0] in ("新需求一", "新需求二")  # updated_at 最新在前
    assert titles[-1] == "旧需求"
    # 完整顺序 = (updated_at, id) 倒序
    expected = sorted(page["items"], key=lambda i: (i["updated_at"], i["id"]), reverse=True)
    assert [i["id"] for i in page["items"]] == [i["id"] for i in expected]


# ---------------------------------------------------------------------------
# 任务列表(HTTP)
# ---------------------------------------------------------------------------


def test_task_filters_over_http(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    t1 = _mk_task(client, pid, "Form Task", description="input validation")
    t2 = _mk_task(client, pid, "Payment Task", status="in_progress")
    t3 = _mk_task(client, pid, "Old Task")
    t4 = _mk_task(client, pid, "Assigned Task")
    resp = client.post(f"/api/tasks/{t4['id']}/assign", json={"assignee_id": str(world["agent"].id)})
    assert resp.status_code == 200, resp.text
    _backdate(db, Task, t3["id"], 5)

    # 多状态(重复参数)
    page = client.get(
        f"/api/projects/{pid}/tasks", params=[("status", "backlog"), ("status", "in_progress")]
    ).json()
    assert _ids(page) == {t1["id"], t2["id"], t3["id"], t4["id"]}
    # keyword 大小写不敏感(标题)
    page = client.get(f"/api/projects/{pid}/tasks", params={"keyword": "FORM"}).json()
    assert _ids(page) == {t1["id"]}
    # keyword 描述命中
    page = client.get(f"/api/projects/{pid}/tasks", params={"keyword": "validation"}).json()
    assert _ids(page) == {t1["id"]}
    # 既有 assignee_id 过滤保持(可与 status 组合)
    page = client.get(
        f"/api/projects/{pid}/tasks", params={"assignee_id": str(world["agent"].id)}
    ).json()
    assert _ids(page) == {t4["id"]}
    page = client.get(
        f"/api/projects/{pid}/tasks",
        params={"assignee_id": str(world["agent"].id), "status": "backlog"},
    ).json()
    assert _ids(page) == {t4["id"]}
    # 时间窗口:回拨 5 天的被排除
    page = client.get(f"/api/projects/{pid}/tasks", params={"updated_within_days": 3}).json()
    assert _ids(page) == {t1["id"], t2["id"], t4["id"]}
    page = client.get(f"/api/projects/{pid}/tasks", params={"updated_within_days": 30}).json()
    assert _ids(page) == {t1["id"], t2["id"], t3["id"], t4["id"]}
    # 组合:keyword + 时间窗口
    page = client.get(
        f"/api/projects/{pid}/tasks", params={"keyword": "Task", "updated_within_days": 3}
    ).json()
    assert _ids(page) == {t1["id"], t2["id"], t4["id"]}


# ---------------------------------------------------------------------------
# cursor 条件哈希与分页
# ---------------------------------------------------------------------------


def test_cursor_condition_hash_covers_all_filters(client: TestClient, world: dict):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    for i in range(6):
        _mk_req(client, pid, f"需求 {i}", status="backlog" if i % 2 == 0 else "in_progress")

    page1 = client.get(f"/api/projects/{pid}/requirements?limit=2").json()
    assert page1["next_cursor"] is not None
    # 跨筛选条件复用游标 → invalid_request(keyword / 时间窗口 / status)
    for params in ({"keyword": "需求"}, {"updated_within_days": 3}, {"status": "backlog"}):
        resp = client.get(
            f"/api/projects/{pid}/requirements", params={**params, "cursor": page1["next_cursor"]}
        )
        assert resp.status_code == 400, (params, resp.status_code, resp.text)
        assert resp.json()["code"] == "invalid_request"

    # 多值 status 顺序不同 → 条件哈希稳定(排序后入哈希),不拒绝
    p1 = client.get(
        f"/api/projects/{pid}/requirements",
        params=[("status", "backlog"), ("status", "in_progress"), ("limit", "2")],
    ).json()
    assert p1["next_cursor"] is not None
    resp = client.get(
        f"/api/projects/{pid}/requirements",
        params=[("status", "in_progress"), ("status", "backlog"), ("cursor", p1["next_cursor"]), ("limit", "2")],
    )
    assert resp.status_code == 200, resp.text


def test_large_pagination_over_100_no_dup_miss(client: TestClient, world: dict, db: Session):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    for i in range(105):
        req_svc.create_requirement(db, world["admin"], world["project"].id, f"批量 {i}")

    page1 = client.get(f"/api/projects/{pid}/requirements?limit=100").json()
    assert len(page1["items"]) == 100
    assert page1["next_cursor"] is not None
    page2 = client.get(
        f"/api/projects/{pid}/requirements", params={"limit": 100, "cursor": page1["next_cursor"]}
    ).json()
    assert len(page2["items"]) == 5
    assert page2["next_cursor"] is None
    assert len(_ids(page1) | _ids(page2)) == 105  # 不漏
    assert not (_ids(page1) & _ids(page2))  # 不重


# ---------------------------------------------------------------------------
# 服务层(list_requirements / list_tasks 新签名)
# ---------------------------------------------------------------------------


def test_service_list_tasks_new_filters(db: Session, world: dict):
    pid = world["project"].id
    req = req_svc.create_requirement(db, world["admin"], pid, "需求")
    req_svc.set_requirement_status(db, world["admin"], req.code, "backlog")
    t1 = task_svc.create_task(
        db, world["admin"], pid, "Form Task", description="input validation",
        requirement_id=req.code, assignee_id=world["agent"].id,
    )
    task_svc.set_task_status(db, world["agent"], t1.code, "in_progress")
    t2 = task_svc.create_task(
        db, world["admin"], pid, "Payment Task", description="wechat pay", requirement_id=req.code
    )
    task_svc.set_task_status(db, world["agent"], t2.code, "done")
    old = task_svc.create_task(db, world["admin"], pid, "Old Task", requirement_id=req.code)
    _backdate(db, Task, old.code, 5)

    # 多状态
    page = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=["in_progress", "done"], cursor=None, limit=20,
        updated_within_days=None, keyword=None,
    )
    assert {i["id"] for i in page["items"]} == {str(t1.code), str(t2.code)}
    # keyword:标题命中 + 大小写不敏感
    page = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=None, limit=20, updated_within_days=None, keyword="FORM",
    )
    assert [i["id"] for i in page["items"]] == [str(t1.code)]
    # keyword:描述命中
    page = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=None, limit=20, updated_within_days=None, keyword="wechat",
    )
    assert [i["id"] for i in page["items"]] == [str(t2.code)]
    # 时间窗口:回拨的排除/大窗口包含
    page = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=None, limit=20, updated_within_days=3, keyword=None,
    )
    assert {i["id"] for i in page["items"]} == {str(t1.code), str(t2.code)}
    page = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=None, limit=20, updated_within_days=30, keyword=None,
    )
    assert {i["id"] for i in page["items"]} == {str(t1.code), str(t2.code), str(old.code)}


def test_service_list_requirements_new_filters(db: Session, world: dict):
    pid = world["project"].id
    r1 = req_svc.create_requirement(db, world["admin"], pid, "Login 需求", description="form validation")
    req_svc.set_requirement_status(db, world["admin"], r1.code, "backlog")
    r2 = req_svc.create_requirement(db, world["admin"], pid, "Pay 需求")
    req_svc.set_requirement_status(db, world["admin"], r2.code, "in_progress")
    old = req_svc.create_requirement(db, world["admin"], pid, "Old 需求")
    _backdate(db, Requirement, old.code, 5)

    page = req_svc.list_requirements(
        db=db, user=world["member"], project_id=pid, status=["backlog", "in_progress"],
        cursor=None, limit=20, updated_within_days=None, keyword=None,
    )
    assert {i["id"] for i in page["items"]} == {str(r1.code), str(r2.code)}
    page = req_svc.list_requirements(
        db=db, user=world["member"], project_id=pid, status=None, cursor=None, limit=20,
        updated_within_days=None, keyword="LOGIN",
    )
    assert [i["id"] for i in page["items"]] == [str(r1.code)]
    page = req_svc.list_requirements(
        db=db, user=world["member"], project_id=pid, status=None, cursor=None, limit=20,
        updated_within_days=3, keyword=None,
    )
    assert {i["id"] for i in page["items"]} == {str(r1.code), str(r2.code)}


def test_service_updated_within_days_invalid(db: Session, world: dict):
    with pytest.raises(AppError) as e:
        req_svc.list_requirements(
            db=db, user=world["member"], project_id=world["project"].id,
            status=None, cursor=None, limit=20, updated_within_days=0, keyword=None,
        )
    assert e.value.code == "invalid_request"
    with pytest.raises(AppError) as e:
        task_svc.list_tasks(
            db=db, user=world["member"], project_id=world["project"].id,
            requirement_id=None, assignee_id=None, status=None, cursor=None, limit=20,
            updated_within_days=-1, keyword=None,
        )
    assert e.value.code == "invalid_request"


def test_service_order_requirements_updated_at_desc(db: Session, world: dict):
    pid = world["project"].id
    a = req_svc.create_requirement(db, world["admin"], pid, "旧需求")
    b = req_svc.create_requirement(db, world["admin"], pid, "新需求")
    now = datetime.now(timezone.utc)
    db.scalar(select(Requirement).where(Requirement.code == a.code).limit(1)).updated_at = now - timedelta(hours=2)
    db.scalar(select(Requirement).where(Requirement.code == b.code).limit(1)).updated_at = now - timedelta(hours=1)
    db.commit()
    page = req_svc.list_requirements(
        db=db, user=world["member"], project_id=pid, status=None, cursor=None, limit=20,
        updated_within_days=None, keyword=None,
    )
    assert [i["title"] for i in page["items"]] == ["新需求", "旧需求"]


def test_service_order_tasks_updated_at_desc_tiebreak_id(db: Session, world: dict):
    pid = world["project"].id
    _req = req_svc.create_requirement(db, world["admin"], pid, "排序需求")
    req_svc.set_requirement_status(db, world["admin"], _req.code, "backlog")
    t1 = task_svc.create_task(db, world["admin"], pid, "任务一", requirement_id=_req.code)
    t2 = task_svc.create_task(db, world["admin"], pid, "任务二", requirement_id=_req.code)
    t3 = task_svc.create_task(db, world["admin"], pid, "任务三", requirement_id=_req.code)
    now = datetime.now(timezone.utc)
    db.scalar(select(Task).where(Task.code == t1.code).limit(1)).updated_at = now - timedelta(hours=1)
    db.scalar(select(Task).where(Task.code == t2.code).limit(1)).updated_at = now - timedelta(hours=2)
    db.scalar(select(Task).where(Task.code == t3.code).limit(1)).updated_at = now - timedelta(hours=1)  # 与 t1 相同 → id 倒序决胜
    db.commit()
    page = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=None, limit=20, updated_within_days=None, keyword=None,
    )
    items = page["items"]
    expected = sorted(items, key=lambda i: (i["updated_at"], i["id"]), reverse=True)
    assert [i["id"] for i in items] == [i["id"] for i in expected]
    assert items[0]["title"] in ("任务一", "任务三")  # updated_at 最新在前
    assert items[-1]["title"] == "任务二"  # 最旧最后


def test_large_pagination_tasks_service(db: Session, world: dict):
    pid = world["project"].id
    _req = req_svc.create_requirement(db, world["admin"], pid, "分页需求")
    req_svc.set_requirement_status(db, world["admin"], _req.code, "backlog")
    for i in range(105):
        task_svc.create_task(db, world["admin"], pid, f"任务 {i}", requirement_id=_req.code)
    page1 = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=None, limit=100, updated_within_days=None, keyword=None,
    )
    assert len(page1["items"]) == 100
    assert page1["next_cursor"] is not None
    page2 = task_svc.list_tasks(
        db=db, user=world["member"], project_id=pid, requirement_id=None, assignee_id=None,
        status=None, cursor=page1["next_cursor"], limit=100, updated_within_days=None, keyword=None,
    )
    assert len(page2["items"]) == 5
    assert page2["next_cursor"] is None
    assert len(_ids(page1) | _ids(page2)) == 105  # 不漏
    assert not (_ids(page1) & _ids(page2))  # 不重
