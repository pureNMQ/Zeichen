from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, Requirement, Task, User
from app.security import hash_password
from app.tests.conftest import login
from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401
from app.v2.file_models import ProjectFile
from app.v2.resource_refs import ResourceKind, ResourceRef
from app.v2.timeline import append_entry, record_system_event, revise_entry, withdraw_entry
from app.v2.wiki import WikiContent, create_wiki, delete_wiki


NEEDLE = "ModularNeedle"


def _seed(db: Session, actor: User, project_id: UUID) -> dict[str, set[str]]:
    reqs = [Requirement(project_id=project_id, code=f"REQ-{i}", title=f"{NEEDLE} requirement {i}", status="backlog")
            for i in (1, 2)]
    db.add_all(reqs)
    db.flush()
    db.add(Task(project_id=project_id, code="TASK-1", requirement_id="REQ-1", title="Done task", status="done"))
    requirement_ref = ResourceRef(project_id, ResourceKind.REQUIREMENT, "REQ-1")

    def note(text):
        return append_entry(db, actor, requirement_ref, request_id=uuid4(), body=text)["entry_id"]

    first_entry = note(f"First {NEEDLE} note")
    second_entry = note("Superseded initial text")
    revise_entry(db, actor, requirement_ref, UUID(second_entry), request_id=uuid4(), expected_version=1,
                 body=f"Latest {NEEDLE} note")
    outdated = note(f"{NEEDLE} removed by revision")
    revise_entry(db, actor, requirement_ref, UUID(outdated), request_id=uuid4(), expected_version=1, body="Different")
    withdrawn = note(f"{NEEDLE} removed by withdrawal")
    withdraw_entry(db, actor, requirement_ref, UUID(withdrawn), request_id=uuid4(), expected_version=1)

    first_wiki = create_wiki(db, actor.id, project_id, request_id=uuid4(), content=WikiContent(
        title="Body keyword", body="intro\n" + " \n" * 160 + "ß" * 80 + f"    left {NEEDLE} right",
    ))
    second_wiki = create_wiki(db, actor.id, project_id, request_id=uuid4(),
                              content=WikiContent(title="Summary keyword", summary=f"A {NEEDLE} summary"))
    hidden = create_wiki(db, actor.id, project_id, request_id=uuid4(), content=WikiContent(title="Hidden subtree"))
    create_wiki(db, actor.id, project_id, request_id=uuid4(), parent_id=hidden["id"],
                content=WikiContent(title=f"{NEEDLE} under deleted ancestor"))
    delete_wiki(db, actor.id, project_id, hidden["id"], confirmed_count=2)

    active_files = {str(uuid4()), str(uuid4())}
    files = [ProjectFile(project_id=project_id, id=UUID(file_id), name=f"{NEEDLE} diagram.png", media_type="image/png",
                         size=4, sha256="a" * 64, created_by=actor.id) for file_id in active_files]
    files.append(ProjectFile(project_id=project_id, id=uuid4(), name=f"Removed {NEEDLE}", media_type="text/plain",
                             size=4, sha256="b" * 64, deleted_at=datetime.now(UTC), created_by=actor.id))
    db.add_all(files)
    db.flush()
    return {"requirement": {"REQ-1", "REQ-2"}, "timeline": {first_entry, second_entry},
            "wiki": {first_wiki["id"], second_wiki["id"]}, "file": active_files}


def test_web_project_search_returns_current_visible_hits_and_independent_domain_pages(client, db, world):
    project_id = world["project"].id
    other_project = Project(team_id=world["team"].id, name="Private scope")
    db.add(other_project)
    db.flush()
    remote = Requirement(project_id=other_project.id, code="REQ-1", title=f"{NEEDLE} other project", status="backlog")
    db.add(remote)
    expected = _seed(db, world["admin"], project_id)
    world["member"].password_hash = hash_password("synthetic-reader-password")
    db.commit()
    login(client, "admin", "admin-pass-1")
    endpoint = f"/api/v2/projects/{project_id}/search"
    result = client.get(endpoint, params={"q": NEEDLE, "limit": 1})
    assert result.status_code == 200, result.text
    pages = result.json()["domains"]
    assert set(pages) == set(expected)

    for domain, ids in expected.items():
        first = pages[domain]
        second = client.get(endpoint, params={"q": NEEDLE, "domain": domain, "limit": 1,
                                              "cursor": first["next_cursor"]}).json()["domains"][domain]
        hits = first["items"] + second["items"]
        assert {row["id"] for row in hits} == ids
        assert second["next_cursor"] is None
        assert all(row["project_id"] == str(project_id) and NEEDLE in row["snippet"] and "body" not in row for row in hits)
        if domain == "requirement":
            assert hits[0]["done_task_count"] == hits[0]["task_count"] == 1
            assert hits[0]["status"] == "backlog"
        if domain == "timeline":
            assert all(row["href"].endswith(f"#timeline-{row['id']}") and row["requirement_id"] == "REQ-1" for row in hits)
        if domain == "wiki":
            assert "left ModularNeedle right" in hits[0]["snippet"]
        if domain == "file":
            assert all(row["preview_href"].endswith("?inline=true") for row in hits)

    cursor = pages["requirement"]["next_cursor"]
    for params in ({"domain": "file"}, {}, {"domain": "requirement", "q": "different"}):
        mismatch = client.get(endpoint, params={"q": NEEDLE, "limit": 1, "cursor": cursor, **params})
        assert mismatch.status_code == 400 and mismatch.json()["code"] == "invalid_request"
    cross_project = client.get(f"/api/v2/projects/{other_project.id}/search",
                               params={"q": NEEDLE, "limit": 1, "cursor": cursor, "domain": "requirement"})
    assert cross_project.status_code == 400
    login(client, "bob", "synthetic-reader-password")
    cross_actor = client.get(endpoint, params={"q": NEEDLE, "limit": 1, "cursor": cursor, "domain": "requirement"})
    assert cross_actor.status_code == 400 and cross_actor.json()["code"] == "invalid_request"
    hidden = client.get(f"/api/v2/projects/{other_project.id}/search", params={"q": NEEDLE})
    assert hidden.status_code == 404 and "other project" not in hidden.text


def test_project_search_exposes_same_result_shape_in_mcp(mcp_server):
    project_id = UUID(mcp_server["project_id"])
    engine = create_engine(f"sqlite:///{(mcp_server['log_file'].parent / 'e2e.db').as_posix()}")
    try:
        with Session(engine) as db, db.begin():
            actor = db.scalar(select(User).where(User.id == UUID(mcp_server["agent_id"])))
            expected = _seed(db, actor, project_id)
    finally:
        engine.dispose()

    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    assert {"search.project", "search.query"}.issubset(client.list_tools())
    results = client.call("search.project", project_id=str(project_id), query=NEEDLE, domains=["timeline", "wiki"])
    assert set(results["domains"]) == {"timeline", "wiki"}
    for domain in results["domains"]:
        assert {row["id"] for row in results["domains"][domain]["items"]} == expected[domain]
        assert results["domains"][domain]["next_cursor"] is None
    filtered = client.call("search.project", project_id=str(project_id), filters={"requirement_status": "backlog"})
    assert set(filtered["domains"]) == {"requirement"}
    assert {row["id"] for row in filtered["domains"]["requirement"]["items"]} == expected["requirement"]


def test_selected_project_search_pages_duplicate_short_codes_and_rechecks_access(client, db, world):
    primary = world["project"].id
    other = Project(team_id=world["team"].id, name="Selected scope")
    db.add(other)
    db.flush()
    projects = {primary: _seed(db, world["admin"], primary), other.id: _seed(db, world["admin"], other.id)}
    membership = ProjectMember(project_id=other.id, user_id=world["member"].id, role="viewer")
    db.add(membership)
    world["member"].password_hash = hash_password("synthetic-reader-password")
    db.commit()
    login(client, "bob", "synthetic-reader-password")

    endpoint = f"/api/v2/projects/{primary}/search"
    params = {"q": NEEDLE, "include_project": str(other.id), "limit": 1}
    response = client.get(endpoint, params=params)
    assert response.status_code == 200, response.text
    pages = response.json()["domains"]
    for domain, first in pages.items():
        current = first
        hits = list(first["items"])
        while current["next_cursor"]:
            response = client.get(endpoint, params={**params, "domain": domain, "cursor": current["next_cursor"]})
            assert response.status_code == 200, response.text
            current = response.json()["domains"][domain]
            hits += current["items"]
        assert len(hits) == 4
        assert {(item["project_id"], item["id"]) for item in hits} == {
            (str(project), item_id) for project, domains in projects.items() for item_id in domains[domain]
        }
        if domain == "requirement":
            assert all(item["task_count"] == 1 for item in hits if item["id"] == "REQ-1")

    cursor = pages["requirement"]["next_cursor"]
    for changed in ({"requirement_status": "backlog"}, {"include_project": str(primary)}):
        mismatch = client.get(endpoint, params={**params, **changed, "domain": "requirement", "cursor": cursor})
        assert mismatch.status_code == 400 and mismatch.json()["code"] == "invalid_request"
    db.delete(membership)
    db.commit()
    denied = client.get(endpoint, params={**params, "domain": "requirement", "cursor": cursor})
    assert denied.status_code == 404 and "Selected scope" not in denied.text


def test_search_filters_current_domain_metadata_time_and_file_usage(client, db, world):
    project = world["project"].id
    actor = world["admin"]
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    requirement = Requirement(project_id=project, code="REQ-1", title="Search target", status="done", updated_at=now)
    db.add(requirement)
    db.flush()
    db.add(Task(project_id=project, code="TASK-1", requirement_id="REQ-1", title="Link", status="done"))
    db.flush()
    scope = ResourceRef(project, ResourceKind.REQUIREMENT, "REQ-1")
    event = record_system_event(db, actor.id, scope, event_type="task.closed",
                                event_data={"summary": "Automated task completion"}, source_task="TASK-1")
    file_id = uuid4()
    unused_id = uuid4()
    for item in (file_id, unused_id):
        db.add(ProjectFile(project_id=project, id=item, name="diagram.png", media_type="image/png",
                           size=4, sha256="a" * 64, created_by=actor.id, created_at=now))
    db.flush()
    file_href = ResourceRef(project, ResourceKind.FILE, str(file_id)).path
    wiki = create_wiki(db, actor.id, project, request_id=uuid4(), content=WikiContent(
        title="Reference page", category="Design", tags=["release-v2"], body=f"[diagram]({file_href})",
    ))
    wiki_href = ResourceRef(project, ResourceKind.WIKI, wiki["id"]).path
    db.commit()
    login(client, "admin", "admin-pass-1")
    endpoint = f"/api/v2/projects/{project}/search"

    def search(domain, **params):
        result = client.get(endpoint, params={"domain": domain, **params})
        assert result.status_code == 200, result.text
        return result.json()["domains"][domain]["items"]

    bounded = {"from_at": "2026-11-16T20:00:00+08:00", "to_at": "2026-11-16T12:01:00Z"}
    assert [item["id"] for item in search("requirement", requirement_status="done", **bounded)] == ["REQ-1"]
    assert search("requirement", requirement_status="done", to_at=now.isoformat()) == []
    assert [item["id"] for item in search("timeline", q="Automated", timeline_actor_id=str(actor.id),
                                          timeline_kind="system", timeline_source_task="TASK-1")] == [str(event.id)]
    assert search("timeline", q="Automated", timeline_kind="manual") == []
    assert [item["id"] for item in search("wiki", wiki_category="Design", wiki_tag="release-v2")] == [wiki["id"]]
    assert search("wiki", wiki_category="Design", wiki_tag="release") == []
    assert [item["id"] for item in search("file", file_media_type="IMAGE/PNG", file_uploader_id=str(actor.id),
                                          file_used_at=wiki_href, **bounded)] == [str(file_id)]
    delete_wiki(db, actor.id, project, wiki["id"], confirmed_count=1)
    db.commit()
    assert search("file", file_used_at=wiki_href) == []
    invalid = client.get(endpoint, params={"domain": "file", "from_at": now.isoformat(), "to_at": now.isoformat()})
    assert invalid.status_code == 400 and invalid.json()["code"] == "invalid_request"


def test_file_search_at_timeline_location_matches_current_reference_only(client, db, world):
    project = world["project"].id
    actor = world["admin"]
    db.add(Requirement(project_id=project, code="REQ-1", title="File references", status="done"))
    file_id = uuid4()
    db.add(ProjectFile(project_id=project, id=file_id, name="diagram.png", media_type="image/png",
                       size=4, sha256="a" * 64, created_by=actor.id))
    db.flush()
    scope = ResourceRef(project, ResourceKind.REQUIREMENT, "REQ-1")
    file_href = ResourceRef(project, ResourceKind.FILE, str(file_id)).path
    note = append_entry(db, actor, scope, request_id=uuid4(), body=f"![diagram]({file_href})")
    entry_id = UUID(note["entry_id"])
    db.commit()
    login(client, "admin", "admin-pass-1")
    endpoint = f"/api/v2/projects/{project}/search"
    params = {"domain": "file", "file_used_at": f"{scope.path}#timeline-{entry_id}"}
    matched = client.get(endpoint, params=params)
    assert matched.status_code == 200, matched.text
    assert [item["id"] for item in matched.json()["domains"]["file"]["items"]] == [str(file_id)]

    revise_entry(db, actor, scope, entry_id, request_id=uuid4(), expected_version=1, body="Attachment removed")
    db.commit()
    removed = client.get(endpoint, params=params)
    assert removed.status_code == 200, removed.text
    assert removed.json()["domains"]["file"]["items"] == []
