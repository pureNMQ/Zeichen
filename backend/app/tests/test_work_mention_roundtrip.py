"""Cross-channel work mentions, historical authors, and inbox visibility."""
from uuid import uuid4

import pytest

from app.tests.test_mcp_e2e import channels, mcp_server  # noqa: F401


@pytest.mark.parametrize("kind,source_kind", [("requirements", "requirement"), ("tasks", "task")])
def test_work_mentions_roundtrip(channels, mcp_server, kind, source_kind):
    web, agent = channels
    pid = agent.call("project.create", name=f"{kind} 通知回归")["id"]
    base = f"/api/projects/{pid}"
    inbox = "/api/v2/notifications"
    owner = web.get("/api/users/me").json()
    agent_id = mcp_server["agent_id"]
    owner_link = f"[@主人](/projects/{pid}/people/{owner['id']})"
    agent_link = f"[@助手](/projects/{pid}/people/{agent_id})"
    initial = {"title": "交付", "request_id": str(uuid4()),
               "description": f"{agent_link} {agent_link} 示例：`{owner_link}`"}
    if kind == "tasks":
        initial["requirement_id"] = agent.call("requirements.create", project_id=pid, title="父需求")["id"]

    def owner_notes():
        return [n for n in web.get(inbox).json()["items"] if n["project_id"] == pid]

    created = web.post(f"{base}/{kind}", json=initial)
    assert created.status_code == 201, created.text
    code = created.json()["id"]
    target = {"project_id": pid, "id": code}
    assert web.post(f"{base}/{kind}", json=initial).json()["id"] == code
    [shared] = owner_notes()
    assert shared["source_kind"] == source_kind and shared["source_code"] == code
    body_path = f"/projects/{pid}/{kind}/{code}"
    if kind == "requirements":
        body_path += "?tab=body"
    assert shared["source_path"] == body_path
    assert shared["source_version"] == 1 and shared["mentioned_user_ids"] == [agent_id]
    assert shared["visibility"] == "shared"
    assert agent.call("notifications.get", id=shared["id"]) == shared
    agent.call("notifications.mark_read", id=shared["id"])
    assert web.get(f"{inbox}/{shared['id']}").json()["read_by_id"] == agent_id

    edited = agent.call(f"{kind}.update", **target, expected_version=1, description=owner_link)
    assert edited["version"] == 2
    private, original = owner_notes()
    assert original["id"] == shared["id"]
    assert private["source_version"] == 2 and private["actor_id"] == agent_id
    assert private["visibility"] == "owner_only" and private["mentioned_user_ids"] == [owner["id"]]
    assert private["source_path"] == body_path
    assert "not_found" in agent.call("notifications.get", id=private["id"])["error"]
    assert "not_found" in agent.call("notifications.mark_read", id=private["id"])["error"]
    assert not web.get(f"{inbox}/{private['id']}").json()["read_at"]

    # Editing around an existing mention, stale writes and restoring an old body all stay silent.
    assert agent.call(f"{kind}.update", **target, expected_version=2, description=f"请查阅 {owner_link}")["version"] == 3
    edit_url = f"/api/{kind}/{code}?project_id={pid}"
    assert web.patch(edit_url, json={"description": agent_link, "expected_version": 1}).status_code == 409
    assert web.patch(edit_url, json={"description": "已完成", "expected_version": 3}).json()["version"] == 4
    assert agent.call("work.restore_version", **target, kind=kind, version=2, expected_version=4)["version"] == 5
    assert {n["id"] for n in owner_notes()} == {private["id"], shared["id"]}

    version_url = f"{base}/{kind}/{code}/versions"
    history = web.get(version_url).json()
    assert history == agent.call("work.versions", **target, kind=kind)
    authors = [(v["actor_id"], v["actor_name"], v["actor_is_agent"]) for v in history["items"]]
    human = (owner["id"], owner["display_name"], False)
    bot = (agent_id, "agent-e2e", True)
    assert authors == [bot, human, bot, bot, human]
    restored = web.get(f"{version_url}/5").json()
    assert restored == agent.call("work.read_version", **target, kind=kind, version=5)
    assert restored["actor_id"] == agent_id and restored["description"] == owner_link

    assert agent.call(f"{kind}.delete", **target)["deleted"]
    assert not owner_notes() and web.get(f"{inbox}/{shared['id']}").status_code == 404
    assert "not_found" in agent.call("notifications.get", id=shared["id"])["error"]
    assert web.post(f"/api/{kind}/{code}/restore?project_id={pid}").status_code == 200
    assert {n["id"] for n in owner_notes()} == {private["id"], shared["id"]}
    assert agent.call("notifications.get", id=shared["id"])["read_by_id"] == agent_id
