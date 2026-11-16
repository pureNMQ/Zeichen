"""附属 Agent(ADR 0004 / REQ-48):成员自有、权限继承、key 管辖矩阵。"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, ProjectMember, User
from app.services import agents as svc
from app.services import members as members_svc
from app.services import permissions as perms
from app.services import projects as projects_svc
from app.tests.conftest import login


def _give_bob_password(client, db):
    """bob 走一遍 pending-password 流程,获得可登录密码。"""
    login(client, "bob", "whatever-1")
    client.post("/api/auth/set-password", json={"password": "bob-pass-1"})
    db.expire_all()


def _admin(client):
    login(client, "admin", "admin-pass-1")
    return client


class TestCreateAffiliatedAgent:
    def test_member_creates_own_agent(self, client, db, world):
        _admin(client)
        resp = client.post("/api/my-agent", json={"username": "admin-bot"})
        assert resp.status_code == 201, resp.text
        body = resp.json()["agent"]
        assert body["username"] == "admin-bot"
        assert body["is_agent"] is True
        assert body["active_keys"] == 0

    def test_second_create_conflicts(self, client, db, world):
        _admin(client)
        assert client.post("/api/my-agent", json={"username": "admin-bot"}).status_code == 201
        resp = client.post("/api/my-agent", json={"username": "another-bot"})
        assert resp.status_code == 409

    def test_duplicate_username_conflicts(self, client, db, world):
        _admin(client)
        assert client.post("/api/my-agent", json={"username": "bot-x"}).status_code == 201
        _give_bob_password(client, db)
        login(client, "bob", "bob-pass-1")
        resp = client.post("/api/my-agent", json={"username": "bot-x"})
        assert resp.status_code == 409

    def test_my_agent_empty_state(self, client, db, world):
        _admin(client)
        resp = client.get("/api/my-agent")
        assert resp.status_code == 200
        assert resp.json() == {"agent": None}

    def test_unauthenticated_denied(self, client, db, world):
        assert client.post("/api/my-agent", json={"username": "x"}).status_code == 401

    def test_old_agents_endpoints_removed(self, client, db, world):
        _admin(client)
        assert client.get("/api/agents").status_code == 404
        assert client.post("/api/agents", json={"username": "x"}).status_code in (404, 405)


class TestKeyJurisdiction:
    def test_issue_and_list_keys(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "key-bot"})
        resp = client.post("/api/my-agent/keys", json={"note": "首次"})
        assert resp.status_code == 201
        assert resp.headers["Cache-Control"] == "no-store"
        assert len(resp.json()["token"]) > 20
        detail = client.get("/api/my-agent").json()["agent"]
        assert detail["active_keys"] == 1
        assert detail["keys"][0]["note"] == "首次"
        assert "token" not in detail["keys"][0]

    def test_no_key_reveal_route_even_for_owner(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "reveal-bot"})
        key = client.post("/api/my-agent/keys", json={"note": None}).json()
        reveal = client.post(
            f"/api/my-agent/keys/{key['id']}/reveal", json={"password": "admin-pass-1"}
        )
        assert reveal.status_code == 404
        assert key["token"] not in reveal.text
        assert set(ApiKey.__table__.columns.keys()).isdisjoint({"token_encrypted", "token"})

    def test_owner_revoke(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "revoke-bot"})
        key = client.post("/api/my-agent/keys", json={"note": None}).json()
        assert client.delete(f"/api/my-agent/keys/{key['id']}").status_code == 200
        detail = client.get("/api/my-agent").json()["agent"]
        assert detail["active_keys"] == 0
        # REQ-53:吊销的 key 条目即时从列表消失,与活跃计数一致
        assert [k["id"] for k in detail["keys"]] == []
        assert db.scalar(select(ApiKey.revoked_at).where(ApiKey.id == uuid.UUID(key["id"]))) is not None

    def test_admin_emergency_revoke_only(self, client, db, world):
        """admin 不可签发/回看他人 agent 的 key,仅可紧急吊销(ADR 0004 §4)。"""
        _give_bob_password(client, db)
        bob = world["member"]
        agent = svc.create_agent(db, bob, "bob-bot")
        key, _token = svc.issue_key(db, bob, None)
        _admin(client)
        resp = client.post(f"/api/members/{bob.id}/agent/revoke-keys")
        assert resp.status_code == 200
        assert resp.json() == {"revoked": 1}
        assert db.scalar(select(ApiKey.revoked_at).where(ApiKey.id == key.id)) is not None
        # 无 agent 的成员:紧急吊销 404
        empty = client.post(f"/api/members/{world['agent'].id}/agent/revoke-keys")
        assert empty.status_code in (404,)


class TestPermissionInheritance:
    def test_reactivation_preserves_identity_but_revoked_keys_stay_revoked(self, client, db, world):
        _admin(client)
        agent = client.post("/api/my-agent", json={"username": "paused-bot"}).json()["agent"]
        key = client.post("/api/my-agent/keys", json={}).json()
        assert client.delete("/api/my-agent").status_code == 200
        assert client.get("/api/my-agent").json()["agent"] is None
        inactive = client.get("/api/my-agent/inactive").json()
        assert [item["id"] for item in inactive] == [agent["id"]]

        path = f"/api/my-agent/inactive/{agent['id']}/reactivate"
        _give_bob_password(client, db)
        login(client, "bob", "bob-pass-1")
        assert client.post(path).status_code == 404

        _admin(client)
        replacement = client.post("/api/my-agent", json={"username": "temporary-bot"})
        assert replacement.status_code == 201
        assert client.post(path).status_code == 409
        assert client.delete("/api/my-agent").status_code == 200

        restored = client.post(path)
        assert restored.status_code == 200
        assert restored.json()["agent"]["id"] == agent["id"]
        assert restored.json()["agent"]["keys"] == []
        assert db.get(ApiKey, uuid.UUID(key["id"])).revoked_at is not None

    def test_agent_inherits_owner_project_role(self, db, world):
        bob = world["member"]
        agent = svc.create_agent(db, bob, "bob-bot")
        project_id = world["project"].id
        assert perms.get_project_role(db, agent.id, project_id) == "viewer"
        pm = db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == bob.id
            )
        )
        pm.role = "editor"
        db.commit()
        assert perms.get_project_role(db, agent.id, project_id) == "editor"

    def test_admin_owner_agent_sees_all_projects_owner_level(self, db, world):
        agent = svc.create_agent(db, world["admin"], "admin-bot")
        assert perms.is_admin(db, agent.id) is True
        assert perms.get_project_role(db, agent.id, world["project"].id) == "owner"
        projects = projects_svc.list_projects(db, agent)
        assert len(projects) >= 1
        assert all(role == "owner" for _p, role in projects)

    def test_owner_removal_disables_agent(self, db, world):
        bob = world["member"]
        agent = svc.create_agent(db, bob, "bob-bot")
        key, _token = svc.issue_key(db, bob, None)
        members_svc.remove_member(db, world["admin"], bob.id)
        db.refresh(agent)
        assert agent.deleted_at is not None
        assert db.scalar(select(ApiKey.revoked_at).where(ApiKey.id == key.id)) is not None
        assert db.scalar(select(ProjectMember).where(ProjectMember.user_id == agent.id)) is None
        # 判权即失效
        assert perms.get_project_role(db, agent.id, world["project"].id) is None

    def test_agent_cannot_login_web(self, client, db, world):
        svc.create_agent(db, world["admin"], "nologin-bot")
        resp = client.post("/api/auth/login", json={"username": "nologin-bot", "password": "wrong-password"})
        assert resp.status_code == 403

    def test_nested_agent_creation_denied(self, db, world):
        from app.errors import AppError

        with pytest.raises(AppError):
            svc.create_agent(db, world["agent"], "nested")


class TestRecreateAfterAgentSoftDeleted:
    """REQ-51:软删的附属 Agent 不得继续占用 owner_id 唯一性,主人须可重新创建。"""

    def _soft_delete_owned_agent(self, db, owner):
        agent = svc.get_owned_agent(db, owner.id)
        from datetime import datetime, timezone

        agent.deleted_at = datetime.now(timezone.utc)
        db.commit()

    def test_service_recreate_after_soft_delete(self, db, world):
        admin = world["admin"]
        svc.create_agent(db, admin, "gone-bot")
        self._soft_delete_owned_agent(db, admin)
        assert svc.get_owned_agent(db, admin.id) is None
        agent = svc.create_agent(db, admin, "second-bot")
        assert agent.deleted_at is None
        assert svc.get_owned_agent(db, admin.id).username == "second-bot"

    def test_api_recreate_after_soft_delete_201(self, client, db, world):
        _admin(client)
        assert client.post("/api/my-agent", json={"username": "old-bot"}).status_code == 201
        self._soft_delete_owned_agent(db, world["admin"])
        resp = client.post("/api/my-agent", json={"username": "new-bot"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["agent"]["username"] == "new-bot"

    def test_late_unique_violation_becomes_conflict(self, db, world, monkeypatch):
        """并发窗口内查重漏判时,唯一索引兜底转 409 而非 500。"""
        from app.errors import AppError

        admin = world["admin"]
        svc.create_agent(db, admin, "race-bot")
        monkeypatch.setattr(svc, "get_owned_agent", lambda d, owner_id: None)
        with pytest.raises(AppError) as ei:
            svc.create_agent(db, admin, "another-racer")
        assert ei.value.status_code == 409


class TestOwnerSelfDeleteAgent:
    """REQ-52:主人自助删除附属 Agent——软删 + 同事务吊销全部 key。"""

    def test_delete_revokes_keys_and_soft_deletes(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "bye-bot"})
        key = client.post("/api/my-agent/keys", json={"note": None}).json()
        resp = client.delete("/api/my-agent")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"ok": True}
        agent = db.scalar(select(User).where(User.username == "bye-bot"))
        assert agent.deleted_at is not None
        key_id = uuid.UUID(key["id"])
        assert db.scalar(select(ApiKey.revoked_at).where(ApiKey.id == key_id)) is not None
        # 成员页摘要与 my-agent 均回到空态
        assert client.get("/api/my-agent").json() == {"agent": None}

    def test_recreate_after_delete_needs_new_username(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "old-name"})
        assert client.delete("/api/my-agent").status_code == 200
        same = client.post("/api/my-agent", json={"username": "old-name"})
        assert same.status_code == 409
        assert "已删除" in same.json()["message"]
        fresh = client.post("/api/my-agent", json={"username": "fresh-name"})
        assert fresh.status_code == 201, fresh.text

    def test_delete_without_agent_404(self, client, db, world):
        _admin(client)
        assert client.delete("/api/my-agent").status_code == 404


class TestOwnerEditsAgentProfile:
    """REQ-52:主人可改附属 Agent 昵称/头像,含恢复默认头像。"""

    def test_owner_sets_and_removes_agent_avatar(self, client, db, world, tmp_path, monkeypatch):
        from app.config import get_settings

        monkeypatch.setattr(get_settings(), "attachment_storage_dir", tmp_path)
        bob = world["member"]
        svc.create_agent(db, bob, "avatar-bot")
        agent = svc.get_owned_agent(db, bob.id)
        _give_bob_password(client, db)
        login(client, "bob", "bob-pass-1")
        png = b"\x89PNG\r\n\x1a\n" + b"img"
        upload = client.post(
            f"/api/users/{agent.id}/avatar", files={"file": ("a.png", png, "image/png")}
        )
        assert upload.status_code == 200, upload.text
        assert upload.json()["avatar"] is not None
        removed = client.delete(f"/api/users/{agent.id}/avatar")
        assert removed.status_code == 200, removed.text
        assert removed.json()["avatar"] is None
        # 主人改 Agent 昵称
        patched = client.patch(f"/api/users/{agent.id}", json={"nickname": "小助手"})
        assert patched.status_code == 200
        assert patched.json()["nickname"] == "小助手"

    def test_other_member_cannot_touch_agent_profile(self, client, db, world):
        bob = world["member"]
        agent = svc.create_agent(db, world["admin"], "guard-bot")
        _give_bob_password(client, db)
        login(client, "bob", "bob-pass-1")
        assert client.patch(f"/api/users/{agent.id}", json={"nickname": "x"}).status_code == 403
        assert client.delete(f"/api/users/{agent.id}/avatar").status_code == 403
        assert client.delete("/api/my-agent").status_code == 404


class TestMembersPayload:
    def test_members_list_carries_agent_summary(self, client, db, world):
        svc.create_agent(db, world["admin"], "summary-bot")
        _admin(client)
        rows = client.get("/api/members").json()
        me = next(r for r in rows if r["username"] == "admin")
        assert me["agent"] is not None
        assert me["agent"]["username"] == "summary-bot"
        assert "active_keys" in me["agent"]
        other = next(r for r in rows if r["username"] == "bob")
        assert other["agent"] is None
