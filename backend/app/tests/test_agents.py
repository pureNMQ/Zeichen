"""附属 Agent(ADR 0004 / REQ-48):成员自有、权限继承、key 管辖矩阵。"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiKey, ProjectMember
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
        assert len(resp.json()["token"]) > 20
        detail = client.get("/api/my-agent").json()["agent"]
        assert detail["active_keys"] == 1
        assert detail["keys"][0]["note"] == "首次"
        assert "token" not in detail["keys"][0]

    def test_reveal_requires_owner_password(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "reveal-bot"})
        key = client.post("/api/my-agent/keys", json={"note": None}).json()
        bad = client.post(
            f"/api/my-agent/keys/{key['id']}/reveal", json={"password": "wrong"}
        )
        assert bad.status_code == 403
        ok = client.post(
            f"/api/my-agent/keys/{key['id']}/reveal", json={"password": "admin-pass-1"}
        )
        assert ok.status_code == 200
        assert ok.json()["token"] == key["token"]

    def test_owner_revoke(self, client, db, world):
        _admin(client)
        client.post("/api/my-agent", json={"username": "revoke-bot"})
        key = client.post("/api/my-agent/keys", json={"note": None}).json()
        assert client.delete(f"/api/my-agent/keys/{key['id']}").status_code == 200
        detail = client.get("/api/my-agent").json()["agent"]
        assert detail["active_keys"] == 0
        reveal = client.post(
            f"/api/my-agent/keys/{key['id']}/reveal", json={"password": "admin-pass-1"}
        )
        assert reveal.status_code == 409

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
        # admin 的 my-agent 无此 key → 404(不可回看他人 key)
        reveal = client.post(
            f"/api/my-agent/keys/{key.id}/reveal", json={"password": "admin-pass-1"}
        )
        assert reveal.status_code == 404
        # 无 agent 的成员:紧急吊销 404
        empty = client.post(f"/api/members/{world['agent'].id}/agent/revoke-keys")
        assert empty.status_code in (404,)


class TestPermissionInheritance:
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
