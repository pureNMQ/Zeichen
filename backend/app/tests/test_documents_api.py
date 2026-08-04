"""Ticket 04: 文档工作台的层级、目录、版本与 HTTP 行为。"""

from app.tests.conftest import login


def create_document(client, project_id: str, module: str, title: str, **extra) -> dict:
    body = {"title": title, "doc_type": module, **extra}
    response = client.post(f"/api/projects/{project_id}/documents/{module}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create_directory(client, project_id: str, module: str, name: str, parent_id: str | None = None) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/documents/{module}/directories",
        json={"name": name, "parent_id": parent_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def api_metadata(path: str = "/users") -> dict:
    return {
        "endpoint": {"method": "get", "path": path},
        "schema": {"fields": [{"name": "id", "type": "string", "required": True}]},
    }


def test_wiki_tree_lazy_children_move_and_recursive_restore(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    root = create_document(client, pid, "wiki", "根 Wiki", content="v1")
    child = create_document(client, pid, "wiki", "子 Wiki", parent_id=root["id"])
    grandchild = create_document(client, pid, "wiki", "孙 Wiki", parent_id=child["id"])

    root_children = client.get(f"/api/projects/{pid}/documents/wiki/children")
    assert [node["id"] for node in root_children.json()["items"]] == [root["id"]]
    assert root_children.json()["items"][0]["has_children"] is True
    children = client.get(f"/api/projects/{pid}/documents/wiki/children?parent_id={root['id']}")
    assert [node["id"] for node in children.json()["items"]] == [child["id"]]

    path = client.get(f"/api/projects/{pid}/documents/wiki/ancestors/document/{grandchild['id']}")
    assert [node["id"] for node in path.json()["items"]] == [root["id"], child["id"], grandchild["id"]]
    cycle = client.post(f"/api/documents/wiki/{root['id']}/move", json={"parent_id": grandchild["id"]})
    assert cycle.status_code == 400
    duplicate = create_document(client, pid, "wiki", "同名根", content="")
    assert client.post(f"/api/documents/wiki/{child['id']}/move", json={"parent_id": None}).status_code == 200
    duplicate_move = client.post(f"/api/documents/wiki/{duplicate['id']}/move", json={"parent_id": None})
    assert duplicate_move.status_code == 200
    same_name = client.post(f"/api/projects/{pid}/documents/wiki", json={"title": "子 Wiki", "doc_type": "wiki"})
    assert same_name.status_code == 409
    assert client.post(f"/api/documents/wiki/{child['id']}/move", json={"parent_id": root["id"]}).status_code == 200

    impact = client.get(f"/api/documents/wiki/{root['id']}/delete-impact").json()
    assert impact == {"documents": 3, "directories": 0}
    assert client.post(f"/api/documents/wiki/{root['id']}/delete").status_code == 200
    deleted = client.get(f"/api/projects/{pid}/documents/wiki/deleted").json()["items"]
    assert {node["id"] for node in deleted} >= {root["id"], child["id"], grandchild["id"]}
    assert client.post(f"/api/documents/wiki/{root['id']}/restore").status_code == 200


def test_directory_tree_module_isolation_and_atomic_restore_conflict(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    glossary_root = create_directory(client, pid, "glossary", "基础")
    glossary_child = create_directory(client, pid, "glossary", "协议", glossary_root["id"])
    term = create_document(client, pid, "glossary", "MCP", directory_id=glossary_child["id"])
    api_root = create_directory(client, pid, "api", "服务")

    assert client.post(
        f"/api/projects/{pid}/documents/api", json={"title": "非法", "doc_type": "api", "directory_id": glossary_root["id"], "metadata": api_metadata()}
    ).status_code == 400
    assert client.post(f"/api/directories/glossary/{glossary_root['id']}/move", json={"parent_id": glossary_child["id"]}).status_code == 400
    children = client.get(f"/api/projects/{pid}/documents/glossary/children?parent_id={glossary_root['id']}").json()["items"]
    assert [node["id"] for node in children] == [glossary_child["id"]]
    leaf = client.get(f"/api/projects/{pid}/documents/glossary/children?parent_id={glossary_child['id']}").json()["items"]
    assert [node["id"] for node in leaf] == [term["id"]]

    assert client.post(f"/api/directories/glossary/{glossary_root['id']}/delete").status_code == 200
    # 已删除的根同级创建同名目录，令整个子树恢复必须原子失败。
    create_directory(client, pid, "glossary", "基础")
    restored = client.post(f"/api/directories/glossary/{glossary_root['id']}/restore")
    assert restored.status_code == 409
    deleted = client.get(f"/api/projects/{pid}/documents/glossary/deleted").json()["items"]
    assert {node["id"] for node in deleted} >= {glossary_root["id"], glossary_child["id"], term["id"]}
    assert api_root["module_type"] == "api"


def test_api_versions_snapshot_title_content_and_metadata(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    definition = create_document(client, pid, "api", "用户查询", content="v1", metadata=api_metadata("/users"))
    updated = client.patch(
        f"/api/documents/api/{definition['id']}",
        json={"title": "成员查询", "content": "v2", "metadata": api_metadata("/members")},
    )
    assert updated.status_code == 200
    versions = client.get(f"/api/documents/api/{definition['id']}/versions").json()["items"]
    assert versions[0]["title"] == "成员查询"
    assert versions[0]["content"] == "v2"
    assert versions[0]["metadata"]["endpoint"]["path"] == "/members"
    rollback = client.post(f"/api/documents/api/{definition['id']}/rollback", json={"version_no": 1})
    assert rollback.status_code == 200
    assert rollback.json()["title"] == "用户查询"
    assert rollback.json()["content"] == "v1"
    assert rollback.json()["metadata"]["endpoint"]["path"] == "/users"


def test_viewer_can_browse_but_cannot_manage_document_tree(client, world, db):
    from app.security import hash_password

    world["member"].password_hash = hash_password("bob-pass-1")
    db.commit()
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    wiki = create_document(client, pid, "wiki", "只读")
    login(client, "bob", "bob-pass-1")
    assert client.get(f"/api/projects/{pid}/documents/wiki/children").status_code == 200
    assert client.get(f"/api/documents/wiki/{wiki['id']}").status_code == 200
    assert client.post(f"/api/documents/wiki/{wiki['id']}/move", json={"parent_id": None}).status_code == 403
    assert client.post(f"/api/projects/{pid}/documents/wiki", json={"title": "不可写", "doc_type": "wiki"}).status_code == 403
