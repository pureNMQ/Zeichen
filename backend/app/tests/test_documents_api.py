"""API reference module removal: endpoints are no longer exposed."""

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


class TestDocumentNodeRoutes:
    """节点路由以短码取回实体后必须传 code(复合主键无 .id,回归防护:REQ-44)。"""

    def test_move_wiki_to_root_and_reparent(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        parent = doc_svc.create_document(db, world["admin"], world["project"].id, "父 Wiki", "wiki", "c", {})
        child = doc_svc.create_document(db, world["admin"], world["project"].id, "子 Wiki", "wiki", "c", {}, parent_id=parent.code)

        resp = client.post(f"/api/documents/wiki/{child.code}/move", json={"parent_id": parent.code, "directory_id": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["parent_id"] == parent.code

        resp = client.post(f"/api/documents/wiki/{child.code}/move", json={"parent_id": None, "directory_id": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == child.code
        assert resp.json()["parent_id"] is None

    def test_move_term_between_directories(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        dir_a = doc_svc.create_directory(db, world["admin"], world["project"].id, "glossary", "目录A")
        dir_b = doc_svc.create_directory(db, world["admin"], world["project"].id, "glossary", "目录B")
        term = doc_svc.create_document(db, world["admin"], world["project"].id, "词条", "glossary", "定义", {}, directory_id=dir_a.code)

        resp = client.post(f"/api/documents/glossary/{term.code}/move", json={"parent_id": None, "directory_id": dir_b.code})
        assert resp.status_code == 200, resp.text
        assert resp.json()["directory_id"] == dir_b.code

    def test_move_directory_to_root(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        parent = doc_svc.create_directory(db, world["admin"], world["project"].id, "glossary", "父目录")
        child = doc_svc.create_directory(db, world["admin"], world["project"].id, "glossary", "子目录", parent_id=parent.code)

        resp = client.post(f"/api/directories/glossary/{child.code}/move", json={"parent_id": None})
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == child.code
        assert resp.json()["parent_id"] is None

    def test_update_delete_impact_delete_directory_routes(self, client, world, db):
        login(client, "admin", "admin-pass-1")
        doc = doc_svc.create_document(db, world["admin"], world["project"].id, "待改文档", "wiki", "c", {})
        directory = doc_svc.create_directory(db, world["admin"], world["project"].id, "glossary", "待删目录")

        resp = client.patch(f"/api/documents/wiki/{doc.code}", json={"title": "改后标题"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "改后标题"

        assert client.get(f"/api/documents/wiki/{doc.code}/delete-impact").status_code == 200
        assert client.get(f"/api/directories/glossary/{directory.code}/delete-impact").status_code == 200

        resp = client.post(f"/api/documents/wiki/{doc.code}/delete")
        assert resp.status_code == 200, resp.text
        resp = client.post(f"/api/documents/wiki/{doc.code}/restore")
        assert resp.status_code == 200, resp.text

        assert client.post(f"/api/directories/glossary/{directory.code}/delete").status_code == 200
        assert client.post(f"/api/directories/glossary/{directory.code}/restore").status_code == 200
