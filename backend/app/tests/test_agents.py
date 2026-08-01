"""Agent 管理 + API key 生命周期:签发 / 回看(管理员密码验证)/ 独立吊销 / 删除清场。"""

from .conftest import login


def _admin_client(client):
    login(client, "admin", "admin-pass-1")
    return client


def test_create_agent_admin_only(client, db, world):
    resp = client.post("/api/agents", json={"username": "robo", "project_grants": []})
    assert resp.status_code == 401

    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    assert (
        client.post("/api/agents", json={"username": "robo", "project_grants": []}).status_code
        == 403
    )

    _admin_client(client)
    resp = client.post(
        "/api/agents",
        json={
            "username": "robo",
            "project_grants": [
                {"project_id": str(world["project"].id), "role": "editor"}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"] == "robo"
    assert body["grants"] == [
        {"project_id": str(world["project"].id), "name": "demo", "role": "editor"}
    ]

    listing = client.get("/api/agents").json()
    assert any(a["username"] == "robo" for a in listing)


def test_agent_duplicate_username(client, db, world):
    _admin_client(client)
    resp = client.post("/api/agents", json={"username": "agent-a", "project_grants": []})
    assert resp.status_code == 409


def test_issue_and_reveal_key(client, db, world):
    _admin_client(client)
    resp = client.post(
        f"/api/agents/{world['agent'].id}/keys", json={"note": "桌面客户端"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    token = body["token"]
    assert token.startswith("zc_")
    key_id = body["id"]

    keys = client.get(f"/api/agents/{world['agent'].id}/keys").json()
    assert len(keys) == 1
    assert keys[0]["id"] == key_id
    assert "token" not in keys[0]

    # 管理员输入自己密码回看明文
    resp = client.post(
        f"/api/agents/{world['agent'].id}/keys/{key_id}/reveal",
        json={"password": "admin-pass-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["token"] == token

    # 密码错误 → 403
    resp = client.post(
        f"/api/agents/{world['agent'].id}/keys/{key_id}/reveal",
        json={"password": "wrong-pass"},
    )
    assert resp.status_code == 403


def test_revoke_key_independent(client, db, world):
    _admin_client(client)
    k1 = client.post(f"/api/agents/{world['agent'].id}/keys", json={}).json()
    k2 = client.post(f"/api/agents/{world['agent'].id}/keys", json={}).json()

    resp = client.post(f"/api/agents/{world['agent'].id}/keys/{k1['id']}/revoke")
    assert resp.status_code == 200

    keys = client.get(f"/api/agents/{world['agent'].id}/keys").json()
    by_id = {k["id"]: k for k in keys}
    assert by_id[k1["id"]]["revoked_at"] is not None
    assert by_id[k2["id"]]["revoked_at"] is None

    # 吊销后不可回看
    resp = client.post(
        f"/api/agents/{world['agent'].id}/keys/{k1['id']}/reveal",
        json={"password": "admin-pass-1"},
    )
    assert resp.status_code == 409


def test_delete_agent_revokes_keys_and_grants(client, db, world):
    from app.models import ApiKey

    _admin_client(client)
    client.post(f"/api/agents/{world['agent'].id}/keys", json={"note": "n"})
    resp = client.delete(f"/api/agents/{world['agent'].id}")
    assert resp.status_code == 200

    # key 全吊销(DB 侧验证;agent 已软删,列表接口 404)
    keys = db.query(ApiKey).filter(ApiKey.user_id == world["agent"].id).all()
    assert all(k.revoked_at is not None for k in keys)
    assert client.get(f"/api/agents/{world['agent'].id}/keys").status_code == 404

    members = client.get(f"/api/projects/{world['project'].id}/members").json()
    assert "agent-a" not in {m["username"] for m in members}

    # 删除后再签发 → 404
    resp = client.post(f"/api/agents/{world['agent'].id}/keys", json={})
    assert resp.status_code == 404


def test_update_agent_grants(client, db, world):
    _admin_client(client)
    resp = client.patch(
        f"/api/agents/{world['agent'].id}",
        json={"project_grants": [{"project_id": str(world["project"].id), "role": "viewer"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["grants"][0]["role"] == "viewer"
