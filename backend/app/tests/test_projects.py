"""项目:列表可见性(admin 全量/member 已加入)、建项目、成员管理、判权矩阵。"""

from .conftest import login, make_user


def _admin_client(client):
    login(client, "admin", "admin-pass-1")
    return client


def test_list_visibility(client, db, world):
    _admin_client(client)
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["demo"]
    assert resp.json()[0]["my_role"] == "owner"

    carol = make_user(db, "carol", role="member")
    client.post("/api/auth/logout")
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert resp.json()[0]["my_role"] == "viewer"

    login(client, "carol", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "carol-pass-1"})
    resp = client.get("/api/projects")
    assert resp.json() == []


def test_create_project_admin_only(client, db, world):
    resp = client.post("/api/projects", json={"name": "x", "members": []})
    assert resp.status_code == 401

    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert (
        client.post("/api/projects", json={"name": "x", "members": []}).status_code == 403
    )

    _admin_client(client)
    resp = client.post(
        "/api/projects",
        json={
            "name": "网站改版",
            "members": [
                {"user_id": str(world["member"].id), "role": "editor"},
                {"user_id": str(world["agent_owner"].id), "role": "editor"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["my_role"] == "owner"

    detail = client.get(f"/api/projects/{resp.json()['id']}/members").json()
    roles = {m["username"]: m["role"] for m in detail}
    assert roles == {"admin": "owner", "bob": "editor", "a-owner": "editor"}


def test_update_project_name(client, db, world):
    _admin_client(client)
    project_id = str(world["project"].id)
    resp = client.patch(f"/api/projects/{project_id}", json={"name": "改版项目"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "改版项目"
    detail = client.get(f"/api/projects/{project_id}").json()
    assert detail["name"] == "改版项目"


def test_update_project_requires_owner(client, db, world):
    project_id = str(world["project"].id)
    client.post("/api/auth/logout")
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert client.patch(f"/api/projects/{project_id}", json={"name": "x"}).status_code == 403
    assert client.patch(f"/api/projects/{project_id}", json={"description": "x"}).status_code == 403


def test_project_card_and_independent_description_edits(client, db, world):
    _admin_client(client)
    project = client.post("/api/projects", json={
        "name": "协作", "description": " 首份说明 ",
        "members": [{"user_id": str(world["member"].id), "role": "viewer"}],
    }).json()
    url = f"/api/projects/{project['id']}"
    assert project["description"] == "首份说明"
    card = next(p for p in client.get("/api/projects").json() if p["id"] == project["id"])
    assert (card["owner_name"], card["member_count"], card["description"]) == ("admin", 2, "首份说明")
    assert client.patch(url, json={"name": "新名称"}).json()["description"] == "首份说明"
    assert client.patch(url, json={"description": "第二段\n换行"}).json()["name"] == "新名称"
    assert client.get(url).json()["description"] == "第二段\n换行"
    assert client.patch(url, json={"description": " "}).json()["description"] == ""


def test_update_project_empty_name_rejected(client, db, world):
    _admin_client(client)
    resp = client.patch(f"/api/projects/{world['project'].id}", json={"name": "  "})
    assert resp.status_code == 400
    resp = client.patch(f"/api/projects/{world['project'].id}", json={"name": ""})
    assert resp.status_code == 422


def test_update_project_whitespace_trimmed(client, db, world):
    _admin_client(client)
    resp = client.patch(f"/api/projects/{world['project'].id}", json={"name": "  改版项目  "})
    assert resp.status_code == 200
    assert resp.json()["name"] == "改版项目"


def test_add_member_owner_only(client, db, world):
    _admin_client(client)
    project_id = str(world["project"].id)
    carol = make_user(db, "carol", role="member")

    # viewer 成员试图加人 → 403
    client.post("/api/auth/logout")
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    resp = client.post(
        f"/api/projects/{project_id}/members",
        json={"user_id": str(carol.id), "role": "viewer"},
    )
    assert resp.status_code == 403

    # admin(自动 owner)加人成功
    _admin_client(client)
    resp = client.post(
        f"/api/projects/{project_id}/members",
        json={"user_id": str(carol.id), "role": "viewer"},
    )
    assert resp.status_code == 201, resp.text

    # 重复添加 → 409
    assert (
        client.post(
            f"/api/projects/{project_id}/members",
            json={"user_id": str(carol.id), "role": "editor"},
        ).status_code
        == 409
    )


def test_add_non_member_human_rejected(client, db, world):
    """非工作区成员的账号不能被加入项目。"""
    _admin_client(client)
    outsider = make_user(db, "outsider", role=None)
    resp = client.post(
        f"/api/projects/{world['project'].id}/members",
        json={"user_id": str(outsider.id), "role": "viewer"},
    )
    assert resp.status_code == 400


def test_remove_member_last_owner_guard(client, db, world):
    """无 admin 且只剩一个 owner 行时,不能移除最后一名 owner。"""
    from app.models import ProjectMember, WorkspaceMember

    project_id = str(world["project"].id)
    # 抹掉 admin 后,把 bob 提为唯一 owner 行
    db.query(WorkspaceMember).filter(WorkspaceMember.role == "admin").delete()
    db.query(ProjectMember).filter(ProjectMember.user_id == world["member"].id).update(
        {ProjectMember.role: "owner"}
    )
    db.commit()

    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})

    # 移除非 owner 成功(项目成员:a-owner editor)
    resp = client.delete(f"/api/projects/{project_id}/members/{world['agent_owner'].id}")
    assert resp.status_code == 200

    # 唯一 owner 不可移除
    resp = client.delete(f"/api/projects/{project_id}/members/{world['member'].id}")
    assert resp.status_code == 409


def test_update_member_role(client, db, world):
    project_id = str(world["project"].id)
    _admin_client(client)

    resp = client.patch(
        f"/api/projects/{project_id}/members/{world['member'].id}",
        json={"role": "editor"},
    )
    assert resp.status_code == 200
    roles = {m["username"]: m["role"] for m in client.get(f"/api/projects/{project_id}/members").json()}
    assert roles["bob"] == "editor"

    resp = client.patch(
        f"/api/projects/{project_id}/members/{world['member'].id}",
        json={"role": "boss"},
    )
    assert resp.status_code == 422

    outsider = make_user(db, "outsider2", role="member")
    resp = client.patch(
        f"/api/projects/{project_id}/members/{outsider.id}",
        json={"role": "viewer"},
    )
    assert resp.status_code == 404


def test_update_member_role_requires_owner(client, db, world):
    project_id = str(world["project"].id)
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    resp = client.patch(
        f"/api/projects/{project_id}/members/{world['agent_owner'].id}",
        json={"role": "viewer"},
    )
    assert resp.status_code == 403


def test_owner_cannot_be_changed_or_removed_by_ordinary_member_routes(client, db, world):
    from app.models import ProjectMember

    project_id = str(world["project"].id)
    db.add(ProjectMember(project_id=world["project"].id, user_id=world["admin"].id, role="owner"))
    db.commit()
    _admin_client(client)
    assert client.patch(
        f"/api/projects/{project_id}/members/{world['admin'].id}",
        json={"role": "editor"},
    ).status_code == 409
    assert client.delete(f"/api/projects/{project_id}/members/{world['admin'].id}").status_code == 409


def test_transfer_owner_requires_current_password_and_existing_member(client, db, world):
    from app.models import ProjectMember

    project_id = str(world["project"].id)
    db.add(ProjectMember(project_id=world["project"].id, user_id=world["admin"].id, role="owner"))
    db.commit()
    _admin_client(client)

    assert client.post(
        f"/api/projects/{project_id}/owner-transfer",
        json={"user_id": str(world["member"].id), "password": "wrong-pass"},
    ).status_code == 403
    assert client.post(
        f"/api/projects/{project_id}/owner-transfer",
        json={"user_id": "00000000-0000-0000-0000-000000000000", "password": "admin-pass-1"},
    ).status_code == 404

    response = client.post(
        f"/api/projects/{project_id}/owner-transfer",
        json={"user_id": str(world["member"].id), "password": "admin-pass-1"},
    )
    assert response.status_code == 200, response.text
    roles = {
        row["username"]: row["role"]
        for row in client.get(f"/api/projects/{project_id}/members").json()
    }
    assert roles["admin"] == "editor"
    assert roles["bob"] == "owner"


def test_member_candidates(client, db, world):
    from datetime import datetime, timezone

    project_id = str(world["project"].id)
    make_user(db, "carol", role="member")
    make_user(db, "new-admin", role="admin")
    disabled = make_user(db, "disabled", role="member")
    disabled.deleted_at = datetime.now(timezone.utc)
    make_user(db, "old-agent-row", role="member", is_agent=True)
    db.commit()
    _admin_client(client)

    resp = client.get(f"/api/projects/{project_id}/member_candidates")
    assert resp.status_code == 200
    assert {m["username"]: m["workspace_role"] for m in resp.json()} == {
        "carol": "member", "admin": "admin", "new-admin": "admin",
    }
    assert all(not m["is_agent"] for m in resp.json())
    for target, status in [(world["agent"], 400), (disabled, 404)]:
        assert client.post(
            f"/api/projects/{project_id}/members", json={"user_id": str(target.id), "role": "viewer"}
        ).status_code == status

    # viewer 成员无候选人访问权
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert client.get(f"/api/projects/{project_id}/member_candidates").status_code == 403


def test_workspace_admin_can_join_other_admins_project_without_becoming_its_owner(client, db, world):
    make_user(db, "creator", role="admin", with_password="creator-pass-1")
    login(client, "creator", "creator-pass-1")
    project_id = client.post("/api/projects", json={"name": "其他管理员的项目"}).json()["id"]
    route = f"/api/projects/{project_id}"
    _admin_client(client)
    assert client.get(route).json()["my_role"] == "owner"
    assert [row["username"] for row in client.get(f"{route}/members").json()] == ["creator"]

    member_id = str(world["admin"].id)
    assert member_id in [row["id"] for row in client.get(f"{route}/member_candidates").json()]
    assert client.get(f"{route}/people/{member_id}").status_code == 404
    assert client.post(f"{route}/members", json={"user_id": member_id, "role": "viewer"}).status_code == 201
    assert member_id not in [row["id"] for row in client.get(f"{route}/member_candidates").json()]
    assert client.get(f"{route}/people/{member_id}").status_code == 200
    own = next(row for row in client.get(f"{route}/members").json() if row["is_current_user"])
    assert (own["role"], own["workspace_role"]) == ("viewer", "admin")
    assert client.post(f"{route}/owner-transfer", json={
        "user_id": member_id, "password": "admin-pass-1"
    }).status_code == 403
    assert client.delete(f"{route}/members/{member_id}").status_code == 200
    assert client.get(route).json()["my_role"] == "owner"
    assert client.get(f"{route}/people/{member_id}").status_code == 404


def test_project_access_matrix(client, db, world):
    project_id = str(world["project"].id)
    outsider = make_user(db, "outsider", role="member")

    _admin_client(client)
    assert client.get(f"/api/projects/{project_id}").status_code == 200

    client.post("/api/auth/logout")
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert client.get(f"/api/projects/{project_id}").status_code == 200
    members = client.get(f"/api/projects/{project_id}/members")
    assert members.status_code == 200
    assert {row["username"]: row["role"] for row in members.json()} == {
        "bob": "viewer",
        "a-owner": "editor",
    }
    assert client.post(
        f"/api/projects/{project_id}/members",
        json={"user_id": str(outsider.id), "role": "viewer"},
    ).status_code == 403

    login(client, "outsider", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "out-pass-1"})
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    assert client.get("/api/projects/00000000-0000-0000-0000-000000000000").status_code == 404
