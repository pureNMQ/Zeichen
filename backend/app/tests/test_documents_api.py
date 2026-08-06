"""Code reference and remaining document workbench behavior."""

from app.tests.conftest import login


def create_library(client, project_id: str, **values) -> dict:
    response = client.post(f"/api/projects/{project_id}/code-reference/libraries", json={
        "name": "Game Runtime", "language": "csharp", "package": "Game.Runtime", **values,
    })
    assert response.status_code == 201, response.text
    return response.json()


def create_symbol(client, library_id: str, **values) -> dict:
    response = client.post(f"/api/code-reference/libraries/{library_id}/symbols", json=values)
    assert response.status_code == 201, response.text
    return response.json()


def test_code_reference_owns_symbols_and_enum_members(client, world):
    login(client, "admin", "admin-pass-1")
    library = create_library(client, str(world["project"].id))
    axis = create_symbol(
        client, library["id"], kind="enum", namespace="Game.Runtime", name="Axis", summary="坐标轴。",
        definition={"underlying_type": "int", "is_flags": False, "members": [
            {"position": 0, "name": "X", "assigned_value": "0", "summary": "X 轴。"},
            {"position": 1, "name": "Y", "assigned_value": "1", "summary": "Y 轴。"},
        ]},
    )
    assert axis["definition"]["members"][1]["name"] == "Y"
    assert axis["kind"] == "enum"
    assert "document_id" not in axis
    assert client.get(f"/api/code-reference/symbols/{axis['id']}").json()["signature"] == "enum Axis"


def test_symbol_kind_contract_and_member_scope(client, world):
    login(client, "admin", "admin-pass-1")
    library = create_library(client, str(world["project"].id))
    controller = create_symbol(
        client, library["id"], kind="class", namespace="Game.Runtime", name="PlayerController", summary="玩家控制器。",
        definition={"type_parameters": [], "interfaces": [], "modifiers": []},
    )
    method = create_symbol(
        client, library["id"], owner_symbol_id=controller["id"], kind="method", name="Move", summary="移动角色。",
        definition={"parameters": [{"name": "force", "type": "float", "summary": "移动力度"}], "returns": {"type": "void"}, "exceptions": [], "type_parameters": [], "modifiers": []},
    )
    assert method["namespace"] == "Game.Runtime"
    assert method["signature"] == "void Move(float force)"
    invalid = client.post(f"/api/code-reference/libraries/{library['id']}/symbols", json={
        "owner_symbol_id": controller["id"], "kind": "constructor", "name": "PlayerController", "summary": "构造。",
        "definition": {"parameters": [], "exceptions": [], "type_parameters": [], "modifiers": []},
    })
    assert invalid.status_code == 201
    bad_interface_constructor = client.post(f"/api/code-reference/libraries/{library['id']}/symbols", json={
        "owner_symbol_id": method["id"], "kind": "constructor", "name": "Bad", "summary": "无效。",
        "definition": {"parameters": [], "exceptions": [], "type_parameters": [], "modifiers": []},
    })
    assert bad_interface_constructor.status_code == 400


def test_code_symbol_versioning_tree_and_recursive_soft_delete(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    library = create_library(client, pid)
    vector = create_symbol(client, library["id"], kind="struct", namespace="Game.Runtime", name="Vector3", summary="向量。", definition={"type_parameters": [], "interfaces": [], "modifiers": []})
    method = create_symbol(client, library["id"], owner_symbol_id=vector["id"], kind="method", name="Normalize", summary="归一化。", definition={"parameters": [], "returns": {"type": "Vector3"}, "exceptions": [], "type_parameters": [], "modifiers": []})
    updated = client.patch(f"/api/code-reference/symbols/{method['id']}", json={"expected_revision": 1, "summary": "返回单位向量。"})
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert client.patch(f"/api/code-reference/symbols/{method['id']}", json={"expected_revision": 1, "summary": "冲突。"}).status_code == 409
    tree = client.get(f"/api/projects/{pid}/code-reference/tree").json()["items"]
    assert tree[0]["node_kind"] == "library"
    assert tree[0]["children"][0]["children"][0]["title"] == "Vector3"
    assert client.post(f"/api/code-reference/symbols/{vector['id']}/delete").status_code == 200
    assert client.get(f"/api/code-reference/symbols/{method['id']}").status_code == 404
    assert client.post(f"/api/code-reference/symbols/{vector['id']}/restore").status_code == 200
    assert client.get(f"/api/code-reference/symbols/{method['id']}").status_code == 200


def test_viewer_can_read_but_not_mutate_code_reference(client, world, db):
    from app.security import hash_password

    world["member"].password_hash = hash_password("bob-pass-1")
    db.commit()
    login(client, "admin", "admin-pass-1")
    library = create_library(client, str(world["project"].id))
    login(client, "bob", "bob-pass-1")
    assert client.get(f"/api/projects/{world['project'].id}/code-reference/libraries").status_code == 200
    assert client.post(f"/api/code-reference/libraries/{library['id']}/symbols", json={
        "kind": "class", "namespace": "Game.Runtime", "name": "ReadOnly", "summary": "只读。",
        "definition": {"type_parameters": [], "interfaces": [], "modifiers": []},
    }).status_code == 403
