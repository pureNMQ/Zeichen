from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import ApiKey, Project, ProjectMember, Team, User, WorkspaceMember
from app.security import generate_api_token, token_digest
from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401
from app.v2.wiki import WikiContent, create_wiki


def _client(mcp_server: dict, token: str | None = None) -> RawMcpClient:
    result = RawMcpClient(mcp_server["url"], token or mcp_server["token"])
    result.initialize()
    return result


def _create(client: RawMcpClient, project_id: str, title: str, **content) -> dict:
    return client.call("wiki.create", project_id=project_id, request_id=str(uuid4()), content={"title": title, **content})


def test_wiki_mcp_edits_a_small_range_and_reads_immutable_versions(mcp_server):
    client = _client(mcp_server)
    project_id = mcp_server["project_id"]
    tools = client._post("tools/list", {})["tools"]
    schemas = {tool["name"]: tool for tool in tools}
    assert "wiki.get" in schemas and "wiki.ancestors" in schemas
    assert schemas["wiki.read"]["annotations"]["readOnlyHint"] is True
    assert schemas["wiki.delete"]["annotations"]["destructiveHint"] is True
    assert set(schemas["wiki.read"]["inputSchema"]["properties"]["mode"]["enum"]) == {"range", "outline", "full"}

    original = "# Intro\r\nfrom\r\n```\r\n# example\r\n```\r\n## End\r\nlast"
    created = _create(client, project_id, "MCP range example", body=original, summary="A short summary", tags=["api"])
    assert set(created) == {"id", "project_id", "version"}
    target = {"project_id": project_id, "id": created["id"]}
    assert "body" not in client.call("wiki.get", **target)
    outline = client.call("wiki.read", **target, mode="outline")
    assert [(item["line"], item["title"]) for item in outline["headings"]] == [(1, "Intro"), (6, "End")]
    assert outline["body"] is None
    selected = client.call("wiki.read", **target, start_line=2, end_line=2)
    assert (selected["body"], selected["total_lines"], selected["next_start_line"]) == ("from\r\n", 7, 3)

    changed = client.call("wiki.edit", **target, expected_version=selected["version"], start_line=2, end_line=2, replacement="updated")
    assert changed == {**target, "version": 2}
    stale = client.call("wiki.edit", **target, expected_version=1, start_line=2, end_line=2, replacement="stale")
    assert "conflict:" in stale["error"]
    assert client.call("wiki.read", **target, mode="full")["body"] == original.replace("from", "updated")
    assert "invalid_request:" in client.call("wiki.read", **target, start_line=8)["error"]

    latest = client.call("wiki.versions", **target, limit=1)
    assert latest["items"][0]["version"] == 2
    assert "body" not in latest["items"][0]
    prior = client.call("wiki.versions", **target, limit=1, cursor=latest["next_cursor"])
    assert prior["items"][0]["version"] == 1 and prior["next_cursor"] is None
    historical = client.call("wiki.read_version", **target, version=1, start_line=1, end_line=2)
    assert historical["body"] == "# Intro\r\nfrom\r\n"
    assert historical["summary"] == "A short summary"
    assert client.call("wiki.restore_version", **target, expected_version=2, from_version=1)["version"] == 3
    assert client.call("wiki.read", **target, mode="full")["body"] == original


def test_wiki_mcp_cursor_is_bound_to_actor_and_project_and_trash_respects_role(mcp_server):
    client = _client(mcp_server)
    project_id = mcp_server["project_id"]
    first = _create(client, project_id, "MCP paging first", summary="b" * 350)
    second = _create(client, project_id, "MCP paging second")
    filters = {"project_id": project_id, "query": "MCP paging", "limit": 1}
    page = client.call("wiki.list", **filters)
    continuation = page["next_cursor"]
    row = page["items"][0]
    assert row["id"] == first["id"] and row["summary"] == "b" * 240 and row["summary_truncated"]
    assert "body" not in row
    assert client.call("wiki.list", **filters, cursor=continuation)["items"][0]["id"] == second["id"]
    assert "invalid_request:" in client.call("wiki.list", **{**filters, "query": "other"}, cursor=continuation)["error"]

    engine = create_engine(f"sqlite:///{(mcp_server['log_file'].parent / 'e2e.db').as_posix()}")
    try:
        with Session(engine) as db, db.begin():
            admin = db.scalar(select(User).where(User.username == "admin"))
            team = db.scalar(select(Team))
            another = Project(team_id=team.id, name="Private remote Wiki project")
            owner = User(username="wiki-mcp-reader", password_hash="", is_agent=False)
            db.add_all([another, owner])
            db.flush()
            agent = User(username="wiki-mcp-read-only", password_hash="", is_agent=True, owner_id=owner.id)
            db.add(agent)
            db.add(WorkspaceMember(team_id=team.id, user_id=owner.id, role="member"))
            db.add(ProjectMember(project_id=UUID(project_id), user_id=owner.id, role="viewer"))
            db.flush()
            token = generate_api_token()
            db.add(ApiKey(user_id=agent.id, token_hash=token_digest(token)))
            remote = create_wiki(db, admin.id, another.id, request_id=uuid4(), content=WikiContent(title="Private contents"))
    finally:
        engine.dispose()

    viewer = _client(mcp_server, token)
    assert "invalid_request:" in viewer.call("wiki.list", **filters, cursor=continuation)["error"]
    foreign_cursor = client.call("wiki.list", **{**filters, "project_id": remote["project_id"]}, cursor=continuation)
    assert "invalid_request:" in foreign_cursor["error"]
    inaccessible = viewer.call("wiki.get", project_id=remote["project_id"], id=remote["id"])
    assert "not_found:" in inaccessible["error"] and "Private contents" not in inaccessible["error"]
    rejected_edit = viewer.call("wiki.edit", project_id=project_id, id=first["id"],
                                expected_version=1, start_line=1, end_line=1, replacement="no permission")
    assert "permission_denied:" in rejected_edit["error"]

    target = {"project_id": project_id, "id": first["id"]}
    impact = client.call("wiki.delete_impact", **target)
    assert impact["affected_count"] == 1
    assert "conflict:" in client.call("wiki.delete", **target, confirmed_count=3)["error"]
    assert client.call("wiki.delete", **target, confirmed_count=1) == {**target, "version": 1, "deleted": True}
    assert "not_found:" in client.call("wiki.get", **target)["error"]
    assert "permission_denied:" in viewer.call("wiki.trash_list", project_id=project_id)["error"]
    trash = client.call("wiki.trash_list", **filters)
    assert trash["items"][0]["id"] == first["id"] and "body" not in trash["items"][0]
    assert client.call("wiki.trash_get", **target)["deleted_at"] is not None
    assert client.call("wiki.restore", **target) == {**target, "version": 1, "restored": True}
    assert client.call("wiki.get", **target)["title"] == "MCP paging first"


def test_wiki_mcp_bounded_reads_never_silently_truncate_body(mcp_server):
    client = _client(mcp_server)
    project_id = mcp_server["project_id"]
    body = "\n".join(f"## Section {i}" for i in range(1, 206))
    created = _create(client, project_id, "MCP outline continuation", body=body)
    target = {"project_id": project_id, "id": created["id"]}
    first = client.call("wiki.read", **target)
    assert (first["start_line"], first["end_line"], first["next_start_line"], first["total_lines"]) == (1, 200, 201, 205)
    assert "invalid_request:" in client.call("wiki.read", **target, start_line=1, end_line=201)["error"]
    outline = client.call("wiki.read", **target, mode="outline")
    assert len(outline["headings"]) == 100 and outline["next_start_line"] == 101
    next_outline = client.call("wiki.read", **target, mode="outline", start_line=outline["next_start_line"])
    assert next_outline["headings"][0]["line"] == 101

    long = _create(client, project_id, "MCP long source line", body="中" * 14000)
    assert "invalid_request:" in client.call("wiki.read", project_id=project_id, id=long["id"], start_line=1)["error"]
