"""工作区成员:全员可读;添加/改角色/移除仅 admin。"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from app.models import PasswordSetupToken

from .conftest import login, make_user


def _admin_client(client):
    login(client, "admin", "admin-pass-1")
    return client


def test_list_members_requires_an_authenticated_session(client, world):
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
    admin = next(row for row in rows if row["username"] == "admin")
    assert admin["is_bootstrap"] is True
    assert admin["is_self"] is True
    assert admin["has_password"] is True
    bob = next(row for row in rows if row["username"] == "bob")
    assert bob["has_password"] is False

    client.post("/api/auth/logout")
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    resp = client.get("/api/members")
    assert resp.status_code == 200
    rows = {row["username"]: row for row in resp.json()}
    assert rows["bob"]["is_self"] is True
    assert rows["admin"]["is_self"] is False


def _setup_token_from_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["token"][0]


def test_setup_link_uses_the_web_origin_not_the_api_origin(client, db, world):
    _admin_client(client)
    response = client.post(
        "/api/members",
        headers={"Host": "localhost:8000"},
        json={"username": "carol", "role": "member"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["password_setup_url"].startswith(
        "http://localhost:5173/set-password?token="
    )


def test_create_member_and_first_login(client, db, world):
    _admin_client(client)
    resp = client.post("/api/members", json={"username": "carol", "role": "member"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "member"
    assert body["password_setup_url"].startswith("http://localhost:5173/set-password?token=")
    raw_token = _setup_token_from_url(body["password_setup_url"])
    stored = db.query(PasswordSetupToken).one()
    assert stored.token_hash != raw_token
    info = client.get(f"/api/auth/password-setup?token={raw_token}")
    assert info.status_code == 200
    assert info.json() == {"username": "carol"}

    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login", json={"username": "carol", "password": "whatever-1"}
    )
    assert resp.status_code == 401

    resp = client.post(
        "/api/auth/set-password-with-token", json={"token": raw_token, "password": "carol-pass-1"}
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/auth/me").json()["username"] == "carol"
    assert client.post(
        "/api/auth/set-password-with-token", json={"token": raw_token, "password": "another-pass-1"}
    ).status_code == 401
    assert client.get(f"/api/auth/password-setup?token={raw_token}").status_code == 401

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "carol", "password": "carol-pass-1"}
    ).status_code == 200
    client.post("/api/auth/logout")
    _admin_client(client)
    assert client.post(f"/api/members/{body['id']}/password-setup-link").status_code == 409


def test_regenerated_setup_link_invalidates_the_previous_link(client, db, world):
    _admin_client(client)
    created = client.post("/api/members", json={"username": "carol", "role": "member"})
    old_token = _setup_token_from_url(created.json()["password_setup_url"])
    user_id = created.json()["id"]

    regenerated = client.post(f"/api/members/{user_id}/password-setup-link")
    assert regenerated.status_code == 200
    new_token = _setup_token_from_url(regenerated.json()["password_setup_url"])
    assert new_token != old_token

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/set-password-with-token", json={"token": old_token, "password": "carol-pass-1"}
    ).status_code == 401
    assert client.post(
        "/api/auth/set-password-with-token", json={"token": new_token, "password": "carol-pass-1"}
    ).status_code == 200


def test_expired_setup_link_is_rejected(client, db, world):
    _admin_client(client)
    created = client.post("/api/members", json={"username": "carol", "role": "member"})
    token = _setup_token_from_url(created.json()["password_setup_url"])
    db.query(PasswordSetupToken).update({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
    db.commit()

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login", json={"username": "carol", "password": "whatever-1"}
    ).status_code == 401
    assert client.post(
        "/api/auth/set-password-with-token", json={"token": token, "password": "carol-pass-1"}
    ).status_code == 401


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


def test_self_role_change_is_blocked(client, db, world):
    _admin_client(client)
    resp = client.patch(
        f"/api/members/{world['admin'].id}", json={"role": "member"}
    )
    assert resp.status_code == 409


def test_bootstrap_role_and_removal_are_locked(client, db, world):
    other_admin = make_user(db, "carol", role="admin", with_password="carol-pass-1")
    client.post("/api/auth/logout")
    login(client, "carol", "carol-pass-1")
    assert client.patch(
        f"/api/members/{world['admin'].id}", json={"role": "member"}
    ).status_code == 409
    assert client.delete(f"/api/members/{world['admin'].id}").status_code == 409


def test_nonbootstrap_member_can_be_changed_or_removed_by_another_admin(client, db, world):
    ordinary_admin = make_user(db, "carol", role="admin", with_password="carol-pass-1")
    other_admin = make_user(db, "dave", role="admin", with_password="dave-pass-1")
    client.post("/api/auth/logout")
    login(client, "dave", "dave-pass-1")

    # The old last-admin guard is gone; only self-operation and bootstrap
    # protection remain. A different admin may change or remove this member.
    assert client.patch(f"/api/members/{ordinary_admin.id}", json={"role": "member"}).status_code == 200
    assert client.delete(f"/api/members/{ordinary_admin.id}").status_code == 200


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


def test_self_removal_is_blocked(client, db, world):
    _admin_client(client)
    resp = client.delete(f"/api/members/{world['admin'].id}")
    assert resp.status_code == 409


def test_member_cannot_manage(client, db, world):
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert client.get("/api/members").status_code == 200
    assert (
        client.post("/api/members", json={"username": "x", "role": "member"}).status_code
        == 403
    )
    assert (
        client.delete(f"/api/members/{world['member'].id}").status_code == 403
    )
