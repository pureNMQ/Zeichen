from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Project, Requirement, Task
from app.security import hash_password
from app.tests.conftest import login
from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401
from app.v2 import timeline
from app.v2.file_models import FileAssociation, ProjectFile
from app.v2.resource_refs import ResourceKind, ResourceRef
from app.v2.wiki import WikiContent, WikiPatch, create_wiki, delete_wiki, update_wiki


def test_usage_merges_live_and_migrated_references_and_hides_deleted_targets(client, db, world, monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", str(tmp_path))
    actor_id, project_id = world["admin"].id, world["project"].id
    login(client, "admin", "admin-pass-1")
    endpoint = f"/api/v2/projects/{project_id}/files"
    blob = b"retained file bytes"
    upload = client.post(endpoint, params={"name": "sample.txt", "request_id": str(uuid4())}, content=blob)
    assert upload.status_code == 201
    file = upload.json()
    file_id = UUID(file["id"])
    usage = f"{endpoint}/{file_id}/usage"

    active = Requirement(project_id=project_id, code="REQ-1", title="Migrated requirement", status="backlog")
    deleted = Requirement(project_id=project_id, code="REQ-2", title="Removed requirement", status="backlog", deleted_at=datetime.now(UTC))
    other = Project(team_id=world["team"].id, name="Other project")
    db.add_all([active, deleted, other])
    db.flush()
    db.add_all([
        Requirement(project_id=other.id, code="REQ-3", title="Remote only", status="backlog"),
        Task(project_id=project_id, code="TASK-1", requirement_id="REQ-2", title="Hidden task", status="backlog"),
    ])
    body = f"[download]({file['href']})"
    doc = create_wiki(db, actor_id, project_id, request_id=uuid4(), content=WikiContent(title="Visible Wiki", body=body))
    parent = create_wiki(db, actor_id, project_id, request_id=uuid4(), content=WikiContent(title="Removed branch"))
    create_wiki(db, actor_id, project_id, request_id=uuid4(), parent_id=parent["id"],
                content=WikiContent(title="Hidden Wiki", body=body))
    delete_wiki(db, actor_id, project_id, parent["id"], confirmed_count=2)
    db.add_all([FileAssociation(project_id=project_id, file_id=file_id, target_kind=kind, target_id=target)
                for kind, target in [("requirements", "REQ-1"), ("requirements", "REQ-2"),
                                     ("requirements", "REQ-3"), ("tasks", "TASK-1"), ("wiki", doc["id"])]])
    db.commit()

    current = client.get(usage).json()
    assert [row["label"] for row in current["items"]] == ["Migrated requirement", "Visible Wiki"]
    assert all(row["current"] for row in current["items"])
    assert client.put(usage, params={"target_kind": "requirements", "target_id": "REQ-3"}).status_code == 404
    assert client.put(usage, params={"target_kind": "tasks", "target_id": "TASK-1"}).status_code == 404

    update_wiki(db, actor_id, project_id, doc["id"], expected_version=1, patch=WikiPatch(title="Current Wiki", body="No link"))
    world["member"].password_hash = hash_password("synthetic-usage-reader")
    db.commit()
    # The explicit association keeps the current document discoverable, independent of the historical Markdown link.
    page1 = client.get(usage, params={"include_history": "true", "limit": 2}).json()
    assert [row["label"] for row in page1["items"]] == ["Migrated requirement", "Current Wiki"]
    page2 = client.get(usage, params={"include_history": "true", "limit": 2, "cursor": page1["next_cursor"]}).json()
    assert page2 == {"items": [{"kind": "wiki", "current": False, "label": "Visible Wiki · v1",
                                "href": f"/projects/{project_id}/wiki/{doc['id']}?version=1"}], "next_cursor": None}
    assert client.get(usage, params={"limit": 2, "cursor": page1["next_cursor"]}).status_code == 400

    target = {"target_kind": "wiki", "target_id": doc["id"]}
    assert client.delete(usage, params=target).json()["changed"] is True
    assert client.delete(usage, params=target).json()["changed"] is False
    assert client.get(file["download_href"]).content == blob
    assert client.put(usage, params=target).json()["changed"] is True
    assert client.put(usage, params=target).json()["changed"] is False
    login(client, "bob", "synthetic-usage-reader")
    assert client.get(usage).status_code == 200
    assert client.delete(usage, params=target).status_code == 403


def test_mcp_can_link_list_and_unlink_same_project_file_without_touching_bytes(mcp_server):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    project_id = mcp_server["project_id"]
    selected = client.call("requirements.create", project_id=project_id, title="MCP file use")
    file_id = uuid4()
    engine = create_engine(f"sqlite:///{(mcp_server['log_file'].parent / 'e2e.db').as_posix()}")
    try:
        with Session(engine) as db, db.begin():
            db.add(ProjectFile(project_id=UUID(project_id), id=file_id, name="known.png", media_type="image/png",
                               size=512, sha256="0" * 64, created_by=UUID(mcp_server["agent_id"])))
    finally:
        engine.dispose()

    scope = {"project_id": project_id, "file_id": str(file_id)}
    association = {**scope, "target_kind": "requirements", "target_id": selected["id"]}
    linked = client.call("files.link", **association)
    assert linked["linked"] and linked["changed"]
    assert client.call("files.usages", **scope) == {"items": [{
        "href": f"/projects/{project_id}/requirements/{selected['id']}", "kind": "requirement",
        "label": "MCP file use", "current": True,
    }], "next_cursor": None}
    unlinked = client.call("files.unlink", **association)
    assert not unlinked["linked"] and unlinked["changed"]
    assert client.call("files.usages", **scope) == {"items": [], "next_cursor": None}


def test_timeline_uses_survive_revision_and_withdrawal_with_scoped_history(client, db, world):
    actor, project_id = world["admin"], world["project"].id
    other = Project(team_id=world["team"].id, name="Other project")
    db.add(other)
    db.flush()
    own = Requirement(project_id=project_id, code="REQ-1", title="Manual", status="backlog")
    remote = Requirement(project_id=other.id, code="REQ-1", title="Remote requirement", status="backlog")
    file_id = uuid4()
    db.add_all([own, remote, ProjectFile(project_id=project_id, id=file_id, name="manual.png",
                                       media_type="image/png", size=1, sha256="0" * 64)])
    db.flush()
    scope = ResourceRef(project_id, ResourceKind.REQUIREMENT, own.code)
    ref = ResourceRef(project_id, ResourceKind.FILE, str(file_id)).path
    remote_ref = ResourceRef(other.id, ResourceKind.FILE, str(file_id)).path
    first = f"[link]({ref})\n\n![preview]({ref})"
    entry = UUID(timeline.append_entry(db, actor, scope, request_id=uuid4(), body=first)["entry_id"])
    timeline.append_entry(db, actor, scope, request_id=uuid4(),
                          body=f"`[link]({ref})`\n\n```md\n[link]({ref})\n```\n\n[remote]({remote_ref})")
    timeline.append_entry(db, actor, ResourceRef(other.id, ResourceKind.REQUIREMENT, remote.code),
                          request_id=uuid4(), body=f"[remote]({remote_ref})")
    timeline.revise_entry(db, actor, scope, entry, request_id=uuid4(), expected_version=1, body=f"![revised]({ref})")
    db.commit()

    login(client, "admin", "admin-pass-1")
    endpoint = f"/api/v2/projects/{project_id}/files/{file_id}/usage"
    anchor = f"#timeline-{entry}"
    current = {"kind": "timeline", "current": True, "label": "Manual · 时间轴", "href": scope.path + anchor}
    historical = {"kind": "timeline", "current": False, "label": "Manual · 时间轴 · v1",
                  "href": f"{scope.path}?timelineVersion=1{anchor}"}
    assert client.get(endpoint).json() == {"items": [current], "next_cursor": None}
    page = client.get(endpoint, params={"include_history": True, "limit": 1}).json()
    assert page["items"] == [current]
    assert client.get(endpoint, params={"include_history": True, "limit": 1, "cursor": page["next_cursor"]}).json() == {
        "items": [historical], "next_cursor": None,
    }

    timeline.withdraw_entry(db, actor, scope, entry, request_id=uuid4(), expected_version=2, reason="Withdrawn")
    db.commit()
    assert client.get(endpoint).json() == {"items": [], "next_cursor": None}
    after = client.get(endpoint, params={"include_history": True}).json()["items"]
    assert [item["current"] for item in after] == [False, False]
    assert after[1] == historical
    revision = f"/api{scope.path}/timeline/{entry}/revisions/1"
    assert client.get(revision).json()["body"] == first
    assert client.get(revision.replace(str(project_id), str(other.id))).status_code == 404
    own.deleted_at = datetime.now(UTC)
    db.commit()
    assert client.get(endpoint, params={"include_history": True}).json()["items"] == []
    assert client.get(revision).status_code == 404
