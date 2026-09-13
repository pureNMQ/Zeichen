"""REQ-4 全局搜索 cursor 分页与域过滤红灯测试(需求 515adbd2 要点 2)。

契约(与既有列表分页规范一致,见 services/pagination.py):
- svc.search(db, user, query, domains=None, cursor=None, limit=None) → {items, next_cursor}
- 默认页大小 DEFAULT_PAGE_SIZE=20;limit 可调(1..MAX_PAGE_SIZE=100)
- 旧行为(各域硬上限 20 条,超出即截断)不再存在
- 末页 next_cursor=None(end of list);非法游标 → invalid_request(400,非 500)
- cursor 条件哈希绑定查询词与域过滤集合,跨条件复用 → invalid_request
- API:GET /api/search 支持 limit/cursor 查询参数,越界 limit → 422
服务层当前不接受 cursor/limit、返回值无 next_cursor → 全部红灯。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import requirements as req_svc
from app.services import search as svc
from app.services import tasks as task_svc
from app.tests.conftest import login


NEEDLE = "分页检索目标"


def seed_requirements(db: Session, world: dict, count: int) -> None:
    for i in range(count):
        req_svc.create_requirement(db, world["admin"], world["project"].id, f"{NEEDLE} 需求 {i:02d}")


def seed_tasks(db: Session, world: dict, count: int) -> None:
    r = req_svc.create_requirement(db, world["admin"], world["project"].id, f"{NEEDLE} 任务挂载")
    req_svc.set_requirement_status(db, world["admin"], r.code, "backlog")
    for i in range(count):
        task_svc.create_task(
            db, world["admin"], world["project"].id, f"{NEEDLE} 任务 {i:02d}", None, r.code
        )


def _ids(page: dict) -> set:
    return {item["id"] for item in page["items"]}


class TestSearchCursorPagination:
    def test_search_returns_cursor_page_shape(self, db: Session, world: dict):
        seed_requirements(db, world, 3)
        result = svc.search(db, world["admin"], NEEDLE)
        assert result["items"]
        assert "next_cursor" in result
        assert result["next_cursor"] is None  # 未满一页即末页

    def test_default_page_size_is_20_and_carries_next_cursor(self, db: Session, world: dict):
        seed_requirements(db, world, 25)
        page1 = svc.search(db, world["admin"], NEEDLE)
        assert len(page1["items"]) == 20
        assert page1["next_cursor"]

    def test_walks_to_end_of_list_without_overlap(self, db: Session, world: dict):
        seed_requirements(db, world, 25)
        page1 = svc.search(db, world["admin"], NEEDLE)
        page2 = svc.search(db, world["admin"], NEEDLE, cursor=page1["next_cursor"])
        assert len(page2["items"]) == 5
        assert page2["next_cursor"] is None
        assert _ids(page1) & _ids(page2) == set()
        assert _ids(page1) | _ids(page2) == _ids({"items": svc.search(db, world["admin"], NEEDLE, limit=100)["items"]})

    def test_limit_controls_page_size(self, db: Session, world: dict):
        seed_requirements(db, world, 25)
        page1 = svc.search(db, world["admin"], NEEDLE, limit=10)
        assert len(page1["items"]) == 10
        assert page1["next_cursor"]
        page2 = svc.search(db, world["admin"], NEEDLE, limit=10, cursor=page1["next_cursor"])
        assert len(page2["items"]) == 10
        page3 = svc.search(db, world["admin"], NEEDLE, limit=10, cursor=page2["next_cursor"])
        assert len(page3["items"]) == 5
        assert page3["next_cursor"] is None
        assert not (_ids(page1) & _ids(page2)) and not (_ids(page2) & _ids(page3))

    def test_limit_can_exceed_legacy_hard_cap(self, db: Session, world: dict):
        """旧行为:各域硬上限 20 条截断;新契约:limit 内全量返回。"""
        seed_requirements(db, world, 25)
        page = svc.search(db, world["admin"], NEEDLE, limit=50)
        assert len(page["items"]) == 25
        assert page["next_cursor"] is None

    def test_rejects_invalid_cursor_as_invalid_request(self, db: Session, world: dict):
        seed_requirements(db, world, 3)
        with pytest.raises(AppError) as error:
            svc.search(db, world["admin"], NEEDLE, cursor="not-a-cursor")
        assert error.value.code == "invalid_request"

    def test_cursor_is_bound_to_query_and_domain_filter(self, db: Session, world: dict):
        seed_requirements(db, world, 3)
        seed_tasks(db, world, 1)
        page = svc.search(db, world["admin"], NEEDLE, domains=["requirement"], limit=1)
        assert page["next_cursor"]
        cursor = page["next_cursor"]
        with pytest.raises(AppError) as error:
            svc.search(db, world["admin"], NEEDLE, domains=["task"], cursor=cursor)
        assert error.value.code == "invalid_request"
        with pytest.raises(AppError) as error:
            svc.search(db, world["admin"], "别的关键词", domains=["requirement"], cursor=cursor)
        assert error.value.code == "invalid_request"
        same = svc.search(db, world["admin"], NEEDLE, domains=["requirement"], cursor=cursor)
        assert len(same["items"]) == 1

    def test_domain_filter_paginates_within_domain(self, db: Session, world: dict):
        seed_requirements(db, world, 25)
        seed_tasks(db, world, 3)
        page1 = svc.search(db, world["admin"], NEEDLE, domains=["task"], limit=2)
        assert [item["domain"] for item in page1["items"]] == ["task", "task"]
        assert page1["next_cursor"]
        page2 = svc.search(db, world["admin"], NEEDLE, domains=["task"], limit=2, cursor=page1["next_cursor"])
        assert len(page2["items"]) == 1
        assert page2["items"][0]["domain"] == "task"
        assert page2["next_cursor"] is None


class TestSearchMemoryDomainPageShape:
    def test_memory_domain_results_carry_page_shape(self, db: Session, world: dict, monkeypatch):
        from app.services import cognee as cognee_module
        from app.services import memory as memory_svc

        class FakeClient:
            def create_dataset(self, name):
                return f"ds-{name}"

            def recall(self, **kwargs):
                return {"answers": [{"answer": f"记忆片段 {i}"} for i in range(3)]}

        monkeypatch.setattr(cognee_module, "CogneeClient", lambda: FakeClient())
        monkeypatch.setattr(memory_svc, "CogneeClient", lambda: FakeClient())
        memory_svc.provision_project(db, world["project"].id, FakeClient())
        db.commit()

        result = svc.search(db, world["member"], NEEDLE, domains=["memory"])
        assert result["items"]
        assert all(item["domain"] == "memory" for item in result["items"])
        assert "next_cursor" in result
        assert result["next_cursor"] is None


class TestSearchApiPagination:
    def test_api_supports_limit_and_cursor_walk(self, client: TestClient, db: Session, world: dict):
        seed_requirements(db, world, 25)
        login(client, "admin", "admin-pass-1")

        page1 = client.get("/api/search", params={"q": NEEDLE, "limit": 10})
        assert page1.status_code == 200, page1.text
        body = page1.json()
        assert len(body["items"]) == 10
        assert body["next_cursor"]

        page2 = client.get("/api/search", params={"q": NEEDLE, "limit": 10, "cursor": body["next_cursor"]})
        assert page2.status_code == 200, page2.text
        body2 = page2.json()
        assert len(body2["items"]) == 10

        page3 = client.get("/api/search", params={"q": NEEDLE, "limit": 10, "cursor": body2["next_cursor"]})
        assert page3.status_code == 200, page3.text
        body3 = page3.json()
        assert len(body3["items"]) == 5
        assert body3["next_cursor"] is None
        assert not ({i["id"] for i in body["items"]} & {i["id"] for i in body2["items"]})

    def test_api_domain_filter_paginates(self, client: TestClient, db: Session, world: dict):
        seed_tasks(db, world, 3)
        login(client, "admin", "admin-pass-1")

        page1 = client.get("/api/search", params={"q": NEEDLE, "domain": "task", "limit": 2})
        assert page1.status_code == 200, page1.text
        body = page1.json()
        assert len(body["items"]) == 2
        assert all(item["domain"] == "task" for item in body["items"])
        assert body["next_cursor"]

        page2 = client.get("/api/search", params={"q": NEEDLE, "domain": "task", "limit": 2, "cursor": body["next_cursor"]})
        assert page2.status_code == 200, page2.text
        body2 = page2.json()
        assert len(body2["items"]) == 1
        assert body2["next_cursor"] is None

    def test_api_rejects_invalid_cursor(self, client: TestClient, db: Session, world: dict):
        seed_requirements(db, world, 3)
        login(client, "admin", "admin-pass-1")
        resp = client.get("/api/search", params={"q": NEEDLE, "cursor": "not-a-cursor"})
        assert resp.status_code == 400, resp.text
        assert resp.json()["code"] == "invalid_request"

    def test_api_rejects_out_of_range_limit(self, client: TestClient, db: Session, world: dict):
        seed_requirements(db, world, 3)
        login(client, "admin", "admin-pass-1")
        assert client.get("/api/search", params={"q": NEEDLE, "limit": 0}).status_code == 422
        assert client.get("/api/search", params={"q": NEEDLE, "limit": 101}).status_code == 422
