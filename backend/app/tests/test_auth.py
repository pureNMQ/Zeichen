"""认证流:首用户引导 / 登录 / 首登设密码 / 改密码 / 退出 / me。"""

from .conftest import login, make_user


def test_bootstrap_status_empty(client):
    resp = client.get("/api/auth/bootstrap")
    assert resp.status_code == 200
    assert resp.json() == {"needs_bootstrap": True}


def test_bootstrap_creates_admin(client, db):
    resp = client.post(
        "/api/auth/bootstrap", json={"username": "alice", "password": "strong-pass-1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_password"] is False
    assert body["user"]["workspace_role"] == "admin"
    assert body["user"]["is_agent"] is False

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"
    assert me.json()["workspace_role"] == "admin"

    status = client.get("/api/auth/bootstrap")
    assert status.json()["needs_bootstrap"] is False


def test_bootstrap_twice_conflict(client, world):
    resp = client.post(
        "/api/auth/bootstrap", json={"username": "alice", "password": "strong-pass-1"}
    )
    assert resp.status_code == 409


def test_login_ok(client, world):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "admin-pass-1"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["needs_password"] is False
    assert body["user"]["username"] == "admin"
    assert body["user"]["workspace_role"] == "admin"
    assert client.get("/api/auth/me").status_code == 200


def test_login_wrong_password(client, world):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong-pass-123"}
    )
    assert resp.status_code == 401


def test_login_unknown_user(client, world):
    resp = client.post(
        "/api/auth/login", json={"username": "nobody", "password": "whatever-1"}
    )
    assert resp.status_code == 401


def test_login_agent_rejected(client, world):
    resp = client.post(
        "/api/auth/login", json={"username": "agent-a", "password": "whatever-1"}
    )
    assert resp.status_code == 403


def test_member_first_login_sets_password(client, db, world):
    # 未设密码的成员:登录 → needs_password + 短令牌(不能访问 me)
    resp = client.post(
        "/api/auth/login", json={"username": "bob", "password": "whatever-1"}
    )
    assert resp.status_code == 200
    assert resp.json()["needs_password"] is True
    assert client.get("/api/auth/me").status_code == 401

    # 设密码 → 获得正式会话
    resp = client.post("/api/auth/set-password", json={"password": "bob-new-pass-1"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["needs_password"] is False
    assert client.get("/api/auth/me").status_code == 200

    # 正式登录可用新密码
    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"username": "bob", "password": "bob-new-pass-1"}
    )
    assert resp.status_code == 200
    assert resp.json()["needs_password"] is False


def test_change_password(client, world):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin-pass-1"})
    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "wrong", "new_password": "new-pass-123"},
    )
    assert resp.status_code == 403

    resp = client.post(
        "/api/auth/change-password",
        json={"old_password": "admin-pass-1", "new_password": "new-pass-123"},
    )
    assert resp.status_code == 200

    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin-pass-1"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "new-pass-123"}
        ).status_code
        == 200
    )


def test_short_password_rejected(client, world):
    resp = client.post(
        "/api/auth/login", json={"username": "admin", "password": "short"}
    )
    assert resp.status_code == 422


def test_logout_clears_session(client, world):
    login(client, "admin", "admin-pass-1")
    assert client.get("/api/auth/me").status_code == 200
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_me_without_login(client, world):
    assert client.get("/api/auth/me").status_code == 401
