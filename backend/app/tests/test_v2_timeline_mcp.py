from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import ProjectMember, Team, User, WorkspaceMember
from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401


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
