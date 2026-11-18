"""Verify governance via human Web requests and Agent MCP calls on the same database."""

from base64 import b64encode
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.main import app
from app.tests.test_mcp_e2e import RawMcpClient, channels, mcp_server


def test_project_and_roster_roundtrip(channels, mcp_server):
    web, agent = channels
    project = agent.call("project.create", name="新项目", description="先由 Agent 起草")
    pid = project["id"]
    url = f"/api/projects/{pid}"
    assert agent.call("project.list") == web.get("/api/projects").json()
    assert agent.call("project.get", id=pid) == web.get(url).json()
    assert web.get(url).json()["description"] == "先由 Agent 起草"
    assert web.patch(url, json={"description": "共同维护"}).status_code == 200
    assert agent.call("project.get", id=pid)["description"] == "共同维护"
    assert agent.call("project.update", project_id=pid, name="项目名")["name"] == web.get(url).json()["name"]

    roster = agent.call("project.members", project_id=pid)["items"]
    assert roster == web.get(f"{url}/members").json()
    owner = roster[0]
    assert owner["username"] == "admin" and owner["is_current_user"] and owner["role"] == "owner"
    assert agent.call("project.remove_member", project_id=pid, user_id=owner["id"]).get("error")
    assert agent.call("workspace.set_member_role", user_id=owner["id"], role="member").get("error")
    assert agent.call("workspace.deactivate_member", user_id=owner["id"]).get("error")

    person = agent.call("workspace.create_member", username="project-invite")
    uid = person["id"]
    assert "password_setup_url" not in person
    # Onboarding through an Agent also requires a human-issued first-login link.
    with TestClient(app) as newcomer:
        assert newcomer.post("/api/auth/login", json={"username": person["username"], "password": "pending-first-login"}).status_code == 401
    profile = agent.call("workspace.set_member_nickname", user_id=uid, nickname="网名")
    assert profile["nickname"] == "网名"
    assert web.patch(f"/api/users/{uid}", json={"nickname": "新昵称"}).status_code == 200
    assert any(p["id"] == uid and p["nickname"] == "新昵称" for p in agent.call("workspace.members")["items"])
    picture = b"GIF89a" + bytes(20)
    assert "invalid_request" in agent.call("workspace.set_member_avatar", user_id=uid, content_type="image/png", data_base64=b64encode(picture).decode())["error"]
    uploaded = agent.call("workspace.set_member_avatar", user_id=uid, content_type="image/gif", data_base64=b64encode(picture).decode())
    assert "error" not in uploaded, uploaded
    assert web.get(uploaded["avatar"]).content == picture
    assert web.post(f"/api/users/{uid}/avatar", files={"file": ("member.gif", picture, "image/gif")}).status_code == 200
    fetched = agent._post("tools/call", {"name": "workspace.member_avatar", "arguments": {"user_id": uid}})["content"][0]
    assert fetched["type"] == "image" and fetched["data"] == b64encode(picture).decode()
    assert agent.call("workspace.remove_member_avatar", user_id=uid)["avatar"] is None
    assert web.get(uploaded["avatar"]).status_code == 404
    for personal_id in (owner["id"], mcp_server["agent_id"]):
        assert "permission_denied" in agent.call("workspace.set_member_nickname", user_id=personal_id, nickname="改名")["error"]
    assert agent.call("project.member_candidates", project_id=pid)["items"] == web.get(f"{url}/member_candidates").json()
    assert uid in {p["id"] for p in web.get(f"{url}/member_candidates").json()}
    assert not agent.call("project.add_member", project_id=pid, user_id=uid, role="viewer").get("error")
    assert any(p["id"] == uid and p["role"] == "viewer" for p in web.get(f"{url}/members").json())
    assert web.patch(f"{url}/members/{uid}", json={"role": "editor"}).status_code == 200
    assert any(p["id"] == uid and p["role"] == "editor" for p in agent.call("project.members", project_id=pid)["items"])
    assert agent.call("project.set_member_role", project_id=pid, user_id=uid, role="viewer")["role"] == "viewer"
    assert agent.call("project.remove_member", project_id=pid, user_id=uid)["removed"]
    assert agent.call("project.add_member", project_id=pid, user_id=mcp_server["agent_id"], role="editor").get("error")

    assert agent.call("workspace.members")["items"] == web.get("/api/members").json()
    assert agent.call("workspace.set_member_role", user_id=uid, role="admin")["role"] == "admin"
    assert any(p["id"] == uid and p["role"] == "admin" for p in web.get("/api/members").json())
    assert web.delete(f"/api/members/{uid}").status_code == 200
    assert agent.call("workspace.inactive_members")["items"] == web.get("/api/members/inactive").json()
    restored = agent.call("workspace.reactivate_member", user_id=uid)
    assert restored["role"] == "member" and "password_setup_url" not in restored
    assert agent.call("workspace.deactivate_member", user_id=uid)["deactivated"]
    assert web.post(f"/api/members/inactive/{uid}/reactivate").status_code == 200

    assert agent.call("project.delete_impact", project_id=pid) == web.get(f"{url}/delete-impact").json()
    assert agent.call("project.delete", project_id=pid)["deleted"]
    assert web.get(url).status_code == 404
    assert web.post(f"/api/projects/trash/{pid}/restore").status_code == 200
    assert agent.call("project.get", id=pid)["name"] == "项目名"


def test_private_views_and_viewer_permissions(channels, mcp_server):
    web, agent = channels
    pid = mcp_server["project_id"]
    url = f"/api/projects/{pid}"
    saved = web.post(f"{url}/filter-views", json={"name": "待办", "entity_type": "requirement", "criteria": {}}).json()
    vid = saved["id"]
    assert agent.call("views.get", id=vid) == saved
    assert agent.call("views.list", project_id=pid)["items"] == [saved]
    assert agent.call("views.update", id=vid, patch={"criteria": {"view_mode": "board"}})["criteria"] == {"view_mode": "board"}
    assert web.get(f"/api/filter-views/{vid}").json()["criteria"] == {"view_mode": "board"}
    second = agent.call("views.create", project_id=pid, name="最近", criteria={"updated_within_days": 7})
    assert web.get(f"/api/filter-views/{second['id']}").json() == second
    assert "conflict" in agent.call("views.update", id=second["id"], patch={"name": "待办"})["error"]
    assert web.delete(f"/api/filter-views/{second['id']}").status_code == 200
    assert "not_found" in agent.call("views.get", id=second["id"])["error"]

    member = agent.call("workspace.create_member", username="view-reader")
    uid = member["id"]
    setup = web.post(f"/api/members/{uid}/password-setup-link").json()["password_setup_url"]
    assert web.post(f"{url}/members", json={"user_id": uid, "role": "viewer"}).status_code == 201
    with TestClient(app) as reader:
        assert reader.post("/api/auth/set-password-with-token", json={
            "token": parse_qs(urlsplit(setup).query)["token"][0], "password": "viewer-pass-1",
        }).status_code == 200
        assert reader.post("/api/my-agent", json={"username": "reader-agent"}).status_code == 201
        credential = reader.post("/api/my-agent/keys", json={}).json()
        restricted = RawMcpClient(mcp_server["url"], credential["token"])
        restricted.initialize()
        assert restricted.call("views.list", project_id=pid)["items"] == []
        assert "not_found" in restricted.call("views.get", id=vid)["error"]
        assert "permission_denied" in restricted.call("workspace.inactive_members")["error"]
        assert "permission_denied" in restricted.call("workspace.create_member", username="unwanted")["error"]
        assert "permission_denied" in restricted.call("workspace.set_member_nickname", user_id=uid, nickname="改名")["error"]
        assert "permission_denied" in restricted.call("project.update", project_id=pid, name="私改")["error"]
        own = restricted.call("views.create", project_id=pid, name="待办", criteria={})
        assert reader.get(f"/api/filter-views/{own['id']}").json() == own
        assert web.delete(f"{url}/members/{uid}").status_code == 200
        assert "not_found" in restricted.call("views.get", id=own["id"])["error"]
        assert reader.get(f"/api/filter-views/{own['id']}").status_code == 404

    assert agent.call("views.delete", id=vid)["deleted"]
    assert web.get(f"/api/filter-views/{vid}").status_code == 404
