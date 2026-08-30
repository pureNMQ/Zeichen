"""全局搜索服务测试(规格书 §4.2 search.query 同后端)。"""

import pytest
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember
from app.services import documents as doc_svc
from app.services import requirements as req_svc
from app.services import search as svc
from app.services import tasks as task_svc
from app.tests.conftest import make_user


def seed(db: Session, world: dict) -> None:
    req_svc.create_requirement(db, world["admin"], world["project"].id, "登录功能需求")
    task_svc.create_task(db, world["admin"], world["project"].id, "实现登录校验", None)
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


class TestMemorySearch:
    def test_memory_domain_with_mocked_client(self, db: Session, world: dict, monkeypatch):
        from app.services import cognee as cognee_module
        from app.services import memory as memory_svc

        class FakeClient:
            def __init__(self):
                pass

            def create_dataset(self, name):
                return f"ds-{name}"

            def recall(self, *, dataset_id, query, session_id=None):
                return {"answers": [{"answer": "记忆片段结果"}]}

        monkeypatch.setattr(cognee_module, "CogneeClient", lambda: FakeClient())
        monkeypatch.setattr(memory_svc, "CogneeClient", lambda: FakeClient())
        memory_svc.provision_project(db, world["project"].id, FakeClient())
        db.commit()
        result = svc.search(db, world["member"], "登录", domains=["memory"])
        assert result["items"]
        assert all(item["domain"] == "memory" for item in result["items"])

    def test_memory_recall_falls_back_to_chunks(self, db: Session, world: dict, monkeypatch):
        from app.services import cognee as cognee_module
        from app.services import memory as memory_svc

        class FakeClient:
            def create_dataset(self, name):
                return f"ds-{name}"

            def recall(self, **kwargs):
                return {"chunks": [{"text": "chunk 片段一"}, {"text": "chunk 片段二"}]}

        monkeypatch.setattr(cognee_module, "CogneeClient", lambda: FakeClient())
        monkeypatch.setattr(memory_svc, "CogneeClient", lambda: FakeClient())
        memory_svc.provision_project(db, world["project"].id, FakeClient())
        db.commit()
        result = svc.search(db, world["member"], "登录", domains=["memory"])
        texts = [item["summary"] for item in result["items"]]
        assert "chunk 片段一" in texts

    def test_memory_skips_projects_without_dataset(self, db: Session, world: dict, monkeypatch):
        from app.services import cognee as cognee_module
        from app.services import memory as memory_svc

        class FakeClient:
            def create_dataset(self, name):
                return f"ds-{name}"

            def recall(self, **kwargs):
                return {"answers": [{"answer": "不该出现"}]}

        monkeypatch.setattr(cognee_module, "CogneeClient", lambda: FakeClient())
        monkeypatch.setattr(memory_svc, "CogneeClient", lambda: FakeClient())
        result = svc.search(db, world["member"], "登录", domains=["memory"])
        assert result["items"] == []

    def test_extract_recall_text_handles_non_dict_payload(self):
        assert svc._extract_recall_text([]) == []
        assert svc._extract_recall_text("plain string") == []
        assert svc._extract_recall_text(None) == []

    def test_memory_domain_no_global_hard_cap(self, db: Session, world: dict, monkeypatch):
        """REQ-4 移除各域 20 条硬上限后:8 项目 × 每项目 recall 前 3 条 = 24 条全量返回。"""
        from app.models import MemoryDataset, ProjectMember
        from app.services import cognee as cognee_module
        from app.services import memory as memory_svc

        class FakeClient:
            def create_dataset(self, name):
                return f"ds-{name}"

            def recall(self, **kwargs):
                return {"answers": [{"answer": f"片段 {i}"} for i in range(3)]}

        monkeypatch.setattr(cognee_module, "CogneeClient", lambda: FakeClient())
        monkeypatch.setattr(memory_svc, "CogneeClient", lambda: FakeClient())
        for i in range(8):
            other = Project(team_id=world["team"].id, name=f"p{i}")
            db.add(other)
            db.commit()
            db.add(ProjectMember(project_id=other.id, user_id=world["member"].id, role="viewer"))
            db.add(MemoryDataset(project_id=other.id, cognee_dataset_id=f"ds-{other.id}"))
            db.commit()
        result = svc.search(db, world["member"], "登录", domains=["memory"], limit=100)
        assert len(result["items"]) == 24
        assert result["next_cursor"] is None


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
        assert svc.search_memory(db, project_ids, "  ") == []

    def test_domain_functions_short_circuit_on_empty_projects(self, db: Session, world: dict):
        assert svc.search_requirements(db, [], "登录") == []
        assert svc.search_tasks(db, [], "登录") == []
        assert svc.search_documents(db, [], "登录") == []
        assert svc.search_memory(db, [], "登录") == []

    def test_project_names_returns_empty_mapping_without_ids(self, db: Session, world: dict):
        assert svc._project_names(db, []) == {}
