"""工作区成员管理:仅 admin;添加/改角色/移除 + 最后管理员守卫。"""

from .conftest import login, make_user


def _admin_client(client):
    login(client, "admin", "admin-pass-1")
    return client


def test_list_members_admin_only(client, world):
    resp = client.get("/api/members")
    assert resp.status_code == 401

    login(client, "bob", "whatever-1")  # bob 无密码 → needs_password,非会话
    assert client.get("/api/members").status_code == 401

    _admin_client(client)
    resp = client.get("/api/members")
    assert resp.status_code == 200
    rows = resp.json()
    usernames = {r["username"]: r["role"] for r in rows}
    assert usernames == {"admin": "admin", "bob": "member"}


def test_create_member_and_first_login(client, db, world):
    _admin_client(client)
    resp = client.post("/api/members", json={"username": "carol", "role": "member"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "member"

    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"username": "carol", "password": "whatever-1"}
    )
    assert resp.status_code == 200
    assert resp.json()["needs_password"] is True


def test_create_member_duplicate(client, db, world):
    _admin_client(client)
    resp = client.post("/api/members", json={"username": "bob", "role": "member"})
    assert resp.status_code == 409


def test_update_role(client, db, world):
    _admin_client(client)
    resp = client.patch(
        f"/api/members/{world['member'].id}", json={"role": "admin"}
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"

    # 新 admin 也能管理成员
    client.post("/api/auth/logout")
    login(client, "bob", "whatever-1")  # bob 还没设密码
    assert client.get("/api/members").status_code == 401  # needs_password 令牌非会话
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert client.get("/api/members").status_code == 200


def test_demote_last_admin_blocked(client, db, world):
    _admin_client(client)
    resp = client.patch(
        f"/api/members/{world['admin'].id}", json={"role": "member"}
    )
    assert resp.status_code == 409


def test_remove_member_revokes_access(client, db, world):
    _admin_client(client)
    resp = client.delete(f"/api/members/{world['member'].id}")
    assert resp.status_code == 200

    # 项目成员行同步清除
    members = client.get(f"/api/projects/{world['project'].id}/members")
    usernames = {m["username"] for m in members.json()}
    assert "bob" not in usernames

    # 已软删用户无法登录
    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"username": "bob", "password": "whatever-1"}
    )
    assert resp.status_code == 401


def test_remove_last_admin_blocked(client, db, world):
    _admin_client(client)
    resp = client.delete(f"/api/members/{world['admin'].id}")
    assert resp.status_code == 409


def test_member_cannot_manage(client, db, world):
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert client.get("/api/members").status_code == 403
    assert (
        client.post("/api/members", json={"username": "x", "role": "member"}).status_code
        == 403
    )
    assert (
        client.delete(f"/api/members/{world['member'].id}").status_code == 403
    )
