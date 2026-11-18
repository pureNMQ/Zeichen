from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import ProjectMember, Team, User, WorkspaceMember
from app.tests.test_mcp_e2e import channels, RawMcpClient, mcp_server  # noqa: F401


def _client(mcp_server: dict) -> RawMcpClient:
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    return client


def test_timeline_wire_supports_retries_revisions_and_withdrawal(mcp_server):
    client = _client(mcp_server)
    root = {"project_id": mcp_server["project_id"]}
    requirement = client.call("requirements.create", **root, title="MCP timeline requirement")
    scope = {**root, "requirement_id": requirement["id"]}
    schema = {item["name"]: item for item in client._post("tools/list", {})["tools"]}
    assert schema["timeline.list"]["annotations"]["readOnlyHint"] is True
    assert schema["timeline.withdraw"]["annotations"]["destructiveHint"] is True
    assert "comment.list" in schema

    request_id = str(uuid4())
    first = client.call("timeline.append", **scope, request_id=request_id, body="Original progress")
    assert set(first) == {"entry_id", "version", "warnings"} and first["version"] == 1
    assert client.call("timeline.append", **scope, request_id=request_id, body="Original progress") == first
    assert "conflict:" in client.call("timeline.append", **scope, request_id=request_id, body="Changed retry")["error"]
    reply = client.call("timeline.append", **scope, request_id=str(uuid4()), body="Reply", reply_to=first["entry_id"])
    assert reply["version"] == 1

    page = client.call("timeline.list", **scope, kind="manual", limit=1)
    assert [row["id"] for row in page["items"]] == [reply["entry_id"]]
    assert "body" not in page["items"][0]
    assert page["items"][0]["reply_to"]["entry_id"] == first["entry_id"]
    earlier = client.call("timeline.list", **scope, kind="manual", limit=1, cursor=page["next_cursor"])
    assert [row["id"] for row in earlier["items"]] == [first["entry_id"]] and earlier["next_cursor"] is None
    assert "invalid_request:" in client.call("timeline.list", **scope, keyword="unrelated", cursor=page["next_cursor"])["error"]

    entry = {**scope, "entry_id": first["entry_id"]}
    context = client.call("timeline.context", **entry, radius=2)
    assert context["anchor_id"] == first["entry_id"]
    assert {first["entry_id"], reply["entry_id"]}.issubset({row["id"] for row in context["items"]})
    revised = client.call("timeline.revise", **entry, request_id=str(uuid4()), expected_version=1, body="Revised progress")
    assert revised["version"] == 2
    assert client.call("timeline.get", **entry)["body"] == "Revised progress"
    stale = client.call("timeline.revise", **entry, request_id=str(uuid4()), expected_version=1, body="Stale")
    assert "conflict:" in stale["error"]

    withdrawn = client.call("timeline.withdraw", **entry, request_id=str(uuid4()), expected_version=2)
    assert withdrawn["version"] == 3
    current = client.call("timeline.get", **entry)
    assert current["withdrawn"] and current["body"] is None
    revisions = client.call("timeline.revisions", **entry)
    assert [item["kind"] for item in revisions["items"]] == ["withdraw", "revise", "create"]
    assert all(item.get("body") is None for item in revisions["items"])
    assert "invalid_request:" in client.call("timeline.revisions", **entry, include_body=True)["error"]
    originals = client.call("timeline.revisions", **entry, include_body=True, limit=3)
    assert [item["body"] for item in originals["items"]] == [None, "Revised progress", "Original progress"]


def test_web_mcp_assignment_rejection_and_timeline_roundtrip(channels, mcp_server):
    web, client = channels
    project = {"project_id": mcp_server["project_id"]}
    base = f"/api/projects/{project['project_id']}"
    assignees = client.call("tasks.assignees", **project)["items"]
    assert web.get(f"{base}/assignees").json() == assignees
    assert any(user["id"] == mcp_server["agent_id"] and user["is_agent"] for user in assignees)
    requirement = web.post(f"{base}/requirements", json={"title": "确认退回"}).json()
    target = {**project, "id": requirement["id"]}
    req = f"{base}/requirements/{requirement['id']}"
    scope = {**project, "requirement_id": requirement["id"]}
    args = {**target, "reason": "补充验收说明", "request_id": str(uuid4())}
    assert "conflict:" in client.call("requirements.reject", **args)["error"]
    assert web.post(f"{req}/status", json={"status": "verifying"}).status_code == 200
    result = client.call("requirements.reject", **args)
    assert result["version"] == 1 and client.call("requirements.reject", **args) == result
    assert web.get(req).json()["status"] == "backlog"
    entries = web.get(f"{req}/timeline", params={"keyword": args["reason"]}).json()["items"]
    assert [row["id"] for row in entries] == [result["entry_id"]]
    client.call("requirements.set_status", **target, status="verifying")
    rejected = web.post(f"{req}/reject", json={"request_id": str(uuid4()), "reason": "补上附件"}).json()
    assert client.call("requirements.get", **target)["status"] == "backlog"
    assert client.call("timeline.get", **scope, entry_id=rejected["entry_id"])["body"] == "打回：补上附件"

    task_id = client.call("tasks.create", **scope, title="验收用例")["id"]
    assert web.post(f"/api/tasks/{task_id}/assign", params=project,
                    json={"assignee_id": mcp_server["agent_id"]}).status_code == 200
    assert client.call("tasks.get", **project, id=task_id)["assignee_id"] == mcp_server["agent_id"]
    original = web.post(f"{req}/timeline", json={
        "source_task": task_id, "request_id": str(uuid4()), "body": "等待复查",
    }).json()["entry_id"]
    assert client.call("timeline.get", **scope, entry_id=original)["source_task"] == task_id
    reply = client.call("timeline.append", **scope, source_task=task_id, reply_to=original,
                        request_id=str(uuid4()), body="已补齐")["entry_id"]
    revision = client.call("timeline.revise", **scope, entry_id=original, request_id=str(uuid4()),
                           expected_version=1, body="等待验收", reason="同步验收用语")
    assert revision["version"] == 2
    filters = {"kind": "manual", "source_task": task_id, "actor_id": mcp_server["agent_id"], "keyword": "补齐"}
    web_reply, = web.get(f"{req}/timeline", params=filters).json()["items"]
    mcp_reply, = client.call("timeline.list", **scope, **filters)["items"]
    assert web_reply["id"] == mcp_reply["id"] == reply
    for row in (web_reply, mcp_reply):
        assert row["reply_to"]["entry_id"] == original and row["reply_to"]["revised"]
        assert row["reply_to"]["actor_name"] == "admin" and row["reply_to"]["body_preview"] == "等待验收"
    by_version = web.get(f"{req}/timeline/{original}/revisions").json()["items"]
    assert [row["actor_name"] for row in by_version] == ["agent-e2e", "admin"]
    assert web.patch(f"{req}/timeline/{original}", json={
        "expected_version": 2, "request_id": str(uuid4()), "body": "完成验收",
    }).status_code == 200
    versions = client.call("timeline.revisions", **scope, entry_id=original, include_body=True, limit=3)["items"]
    assert [(row["actor_name"], row["body"]) for row in versions] == [
        ("admin", "完成验收"), ("agent-e2e", "等待验收"), ("admin", "等待复查"),
    ]


def test_mcp_project_candidates_use_existing_access_scope(mcp_server):
    client = _client(mcp_server)
    project_id = mcp_server["project_id"]
    request = client.call("requirements.create", project_id=project_id, title="Identity candidate requirement")
    database = f"sqlite:///{(mcp_server['log_file'].parent / 'e2e.db').as_posix()}"
    engine = create_engine(database)
    try:
        with Session(engine) as db, db.begin():
            team = db.scalar(select(Team))
            member = User(username="timeline-candidate", is_agent=False, password_hash="")
            private = User(username="timeline-hidden", is_agent=False, password_hash="")
            db.add_all([member, private])
            db.flush()
            db.add_all([WorkspaceMember(team_id=team.id, user_id=user.id, role="member") for user in (member, private)])
            db.add(ProjectMember(project_id=UUID(project_id), user_id=member.id, role="editor"))
            member_id, private_id = str(member.id), str(private.id)
    finally:
        engine.dispose()

    candidates = client.call("project.candidates", project_id=project_id, mode="people", query="timeline-")
    assert [person["id"] for person in candidates["items"]] == [member_id]
    assert client.call("project.person", project_id=project_id, person_id=member_id)["kind"] == "member"
    assert "not_found:" in client.call("project.person", project_id=project_id, person_id=private_id)["error"]
    references = client.call("project.candidates", project_id=project_id, mode="reference", query=request["id"])
    assert references["items"][0]["href"] == f"/projects/{project_id}/requirements/{request['id']}"
