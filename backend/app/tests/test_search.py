"""全局搜索服务测试(规格书 §4.2 search.query 同后端)。"""

from sqlalchemy.orm import Session

from app.models import Project
from app.services import documents as doc_svc
from app.services import requirements as req_svc
from app.services import search as svc
from app.services import tasks as task_svc
from app.tests.conftest import make_user


def seed(db: Session, world: dict) -> None:
    r = req_svc.create_requirement(db, world["admin"], world["project"].id, "登录功能需求")
    req_svc.set_requirement_status(db, world["admin"], r.code, "backlog")
    task_svc.create_task(
        db, world["admin"], world["project"].id, "实现登录校验", None, r.code
    )
    doc_svc.create_document(
        db, world["admin"], world["project"].id, "登录设计文档", "wiki", "这是登录页面的设计说明", {}
    )


class TestKeywordSearch:
    def test_search_requirement(self, db: Session, world: dict):
        seed(db, world)
        result = svc.search(db, world["member"], "登录")
        assert result["items"]
        domains = {item["domain"] for item in result["items"]}
        assert "requirement" in domains
        assert "task" in domains
        assert "document" in domains
        for item in result["items"]:
            assert item["project_name"] == "demo"

    def test_viewer_sees_only_accessible_projects(self, db: Session, world: dict):
        other = Project(team_id=world["team"].id, name="hidden")
        db.add(other)
        db.commit()
        req_svc.create_requirement(db, world["admin"], other.id, "隐藏项目的秘密需求")
        db.commit()
        # member 只属于 demo,看不到 hidden
        result = svc.search(db, world["member"], "秘密")
        assert result["items"] == []

    def test_admin_searches_all_projects(self, db: Session, world: dict):
        other = Project(team_id=world["team"].id, name="hidden")
        db.add(other)
        db.commit()
        req_svc.create_requirement(db, world["admin"], other.id, "跨项目检索目标")
        result = svc.search(db, world["admin"], "跨项目")
        assert result["items"]
        assert all(item["project_name"] in {"demo", "hidden"} for item in result["items"])

    def test_empty_query_returns_nothing(self, db: Session, world: dict):
        assert svc.search(db, world["member"], "   ").get("items") == []

    def test_domain_filter(self, db: Session, world: dict):
        seed(db, world)
        result = svc.search(db, world["member"], "登录", domains=["requirement"])
        assert result["items"]
        assert all(item["domain"] == "requirement" for item in result["items"])


class TestCodeSymbolSearchRemoved:
    def test_code_symbol_search_is_removed(self):
        assert not hasattr(svc, "search_code_symbols")


class TestMemorySearchRemoved:
    """REQ-57:记忆域随记忆系统下线,搜索不再有任何记忆通路。"""

    def test_memory_search_is_removed(self):
        assert not hasattr(svc, "search_memory")

    def test_api_rejects_memory_domain(self, client, db, world):
        from .conftest import login

        login(client, "admin", "admin-pass-1")
        resp = client.get("/api/search", params={"q": "登录", "domain": "memory"})
        assert resp.status_code == 400
        assert resp.json()["code"] == "invalid_request"


class TestEmptyScopeAndEdgeGuards:
    def test_user_without_projects_returns_empty(self, db: Session, world: dict):
        from app.tests.conftest import make_user

        lonely = make_user(db, "lonely", role="member")
        assert svc.search(db, lonely, "登录") == {"items": []}

    def test_domain_functions_short_circuit_on_empty_needle(self, db: Session, world: dict):
        project_ids = [world["project"].id]
        assert svc.search_requirements(db, project_ids, "") == []
        assert svc.search_tasks(db, project_ids, "  ") == []
        assert svc.search_documents(db, project_ids, "") == []

    def test_domain_functions_short_circuit_on_empty_projects(self, db: Session, world: dict):
        assert svc.search_requirements(db, [], "登录") == []
        assert svc.search_tasks(db, [], "登录") == []
        assert svc.search_documents(db, [], "登录") == []

    def test_project_names_returns_empty_mapping_without_ids(self, db: Session, world: dict):
        assert svc._project_names(db, []) == {}
