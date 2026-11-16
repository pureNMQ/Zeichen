"""文档 HTTP API 测试(REQ-59:wiki 单模块、INDEX、双链聚合响应)。"""

import uuid

from app.services import documents as doc_svc
from app.tests.conftest import login


def test_code_reference_routes_are_removed(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    sid = str(uuid.uuid4())

    assert client.get(f"/api/projects/{pid}/code-reference/libraries").status_code == 404
    assert client.post(f"/api/projects/{pid}/code-reference/libraries", json={}).status_code == 404
    assert client.get(f"/api/projects/{pid}/code-reference/tree").status_code == 404
    assert client.post(f"/api/projects/{pid}/code-reference/libraries/{sid}/symbols", json={}).status_code == 404
    assert client.patch(f"/api/code-reference/symbols/{sid}", json={}).status_code == 404
    assert client.post(f"/api/code-reference/symbols/{sid}/rollback", json={}).status_code == 404


def test_directory_routes_are_removed(client, world, db):
    """glossary 合并后目录端点整体下线。"""
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    assert client.get(f"/api/directories/glossary/DIR-1").status_code == 404
    assert client.post(f"/api/projects/{pid}/documents/glossary/directories", json={"name": "x"}).status_code in (404, 422)
    assert client.post(f"/api/documents/glossary/TERM-1/delete").status_code in (404, 422)
    resp = client.post(f"/api/projects/{pid}/documents/glossary", json={"title": "t", "doc_type": "glossary"})
    assert resp.status_code == 422  # doc_type 不再接受 glossary


class TestDocumentNodeRoutes:
    """节点路由以短码取回实体后必须传 code(复合主键无 .id,回归防护:REQ-44)。"""

    def test_move_wiki_to_root_and_reparent(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        parent, _ = doc_svc.create_document(db, world["admin"], world["project"].id, "父 Wiki", "wiki", "c", {})
        child, _ = doc_svc.create_document(db, world["admin"], world["project"].id, "子 Wiki", "wiki", "c", {}, parent_id=parent.code)

        resp = client.post(f"/api/documents/wiki/{child.code}/move", json={"parent_id": parent.code})
        assert resp.status_code == 200, resp.text
        assert resp.json()["parent_id"] == parent.code

        resp = client.post(f"/api/documents/wiki/{child.code}/move", json={"parent_id": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == child.code
        assert resp.json()["parent_id"] is None

    def test_update_delete_impact_delete_restore_routes(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        doc, _ = doc_svc.create_document(db, world["admin"], world["project"].id, "待改文档", "wiki", "c", {})

        resp = client.patch(f"/api/documents/wiki/{doc.code}", json={"title": "改后标题"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "改后标题"

        assert client.get(f"/api/documents/wiki/{doc.code}/delete-impact").status_code == 200

        resp = client.post(f"/api/documents/wiki/{doc.code}/delete")
        assert resp.status_code == 200, resp.text
        resp = client.post(f"/api/documents/wiki/{doc.code}/restore")
        assert resp.status_code == 200, resp.text


class TestAggregatedDetailAndIndex:
    def test_get_returns_links_and_author(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        target, _ = doc_svc.create_document(db, world["admin"], world["project"].id, "目标页", "wiki", "t", {})
        doc, warnings = doc_svc.create_document(
            db, world["admin"], world["project"].id, "链接页", "wiki",
            f"看 [[{target.code}]] 与 [[断链目标]]", {}
        )
        assert warnings is not None

        resp = client.get(f"/api/documents/wiki/{doc.code}")
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["author"]["username"] == "admin"
        outgoing = {item["raw_text"]: item for item in payload["links"]["outgoing"]}
        assert outgoing[target.code]["to_code"] == target.code
        assert outgoing["断链目标"]["broken"] is True

        # 反链在目标页可见
        resp = client.get(f"/api/documents/wiki/{target.code}")
        assert resp.status_code == 200
        assert [item["from_code"] for item in resp.json()["links"]["incoming"]] == [doc.code]

    def test_create_with_frontmatter_and_link_warnings(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        pid = str(world["project"].id)
        resp = client.post(
            f"/api/projects/{pid}/documents/wiki",
            json={
                "title": "frontmatter页",
                "doc_type": "wiki",
                "content": "---\ndoc_kind: decision\nsummary: 摘要\n---\n正文 [[不存在的页]]",
            },
        )
        assert resp.status_code == 201, resp.text
        payload = resp.json()
        assert payload["metadata"]["doc_kind"] == "decision"
        assert payload["reference_warning"]["count"] == 1

    def test_project_index_endpoint(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        pid = str(world["project"].id)
        doc_svc.create_document(
            db, world["admin"], world["project"].id, "决策", "wiki",
            "---\ndoc_kind: decision\nsummary: s\n---\nb", {}
        )
        resp = client.get(f"/api/projects/{pid}/documents/index")
        assert resp.status_code == 200, resp.text
        index = resp.json()
        assert index["total"] >= 1
        assert any(section["kind"] == "decision" for section in index["sections"])
        assert "lint" in index
