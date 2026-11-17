from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from app.models import Activity, Attachment, Comment, Document, DocumentVersion, Requirement, Task
from app.tests.conftest import login
from app.v2.import_legacy_timeline import import_timeline
from app.v2.import_legacy_wiki import import_wiki
from app.v2 import import_legacy_files
from app.v2.file_models import FileAssociation, ProjectFile
from app.v2.timeline_models import TimelineEntry, TimelineFileReference, TimelineRevision
from app.v2.wiki_models import Wiki, WikiReference, WikiVersion


def test_legacy_files_keep_bytes_original_uuid_and_independent_usage(tmp_path, db, world, monkeypatch):
    pid = world["project"].id
    payload = b"%PDF-1.7\nsynthetic fixture"
    attachment = Attachment(project_id=pid, target_type="requirement", target_id="REQ-1",
                            file_name="manual.pdf", size=len(payload), storage_path="unreliable-old-path")
    db.add(attachment)
    db.commit()
    legacy = tmp_path / "legacy"
    source = legacy / str(pid) / f"{attachment.id}.bin"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    target = tmp_path / "v2" / str(pid) / f"{attachment.id}.bin"
    monkeypatch.setattr(import_legacy_files, "file_path", lambda project, ident: target)
    counts, exceptions = import_legacy_files.import_files(db, legacy)
    assert counts == {"files_imported": 1, "associations_imported": 1}
    assert not exceptions
    row = db.get(ProjectFile, (pid, attachment.id))
    assert row.sha256 == sha256(payload).hexdigest()
    assert row.media_type == "application/pdf"
    assert db.get(FileAssociation, (pid, attachment.id, "requirements", "REQ-1")) is not None
    assert source.read_bytes() == target.read_bytes() == payload
    assert import_legacy_files.import_files(db, legacy)[0] == {"already_imported": 1}
    db.add(Document(project_id=pid, code="DOC-1", title="Manual", doc_type="wiki",
                    content=f"[Open](/api/attachments/{attachment.id}/download)"))
    db.flush()
    assert import_wiki(db)[0]["documents_imported"] == 1
    assert db.get(Wiki, (pid, "DOC-1")).body == f"[Open](</projects/{pid}/files/{attachment.id}>)"


def test_import_history_preserves_source_and_does_not_guess_reparented_task(db, world):
    pid = world["project"].id
    actor = world["admin"].id
    timestamp = world["project"].created_at
    file_id = uuid4()
    body = f"retained text [file](/projects/{pid}/files/{file_id})"
    db.add(Requirement(project_id=pid, code="REQ-1", title="Requirement"))
    db.flush()
    db.add(Task(project_id=pid, code="TASK-1", requirement_id="REQ-1", title="Moved Task"))
    comment = Comment(project_id=pid, target_type="requirement", target_id="REQ-1",
                      author_id=actor, body=body, deleted_at=timestamp)
    moved = Activity(project_id=pid, target_type="task", target_id="TASK-1", action="update", summary="关联需求")
    original = Activity(project_id=pid, target_type="requirement", target_id="REQ-1",
                        actor_id=actor, action="status", summary="old event", created_at=timestamp)
    db.add_all([comment, moved, original])
    db.commit()

    counts, exceptions = import_timeline(db)
    assert counts == {"comments_imported": 1, "activity_imported": 1}
    assert [(item.source_id, item.reason) for item in exceptions] == [(str(moved.id), "task_requirement_at_event_unknown")]
    entry = db.get(TimelineEntry, comment.id)
    assert entry.actor_id == actor and entry.occurred_at == comment.created_at
    assert db.get(TimelineRevision, (comment.id, 1)).body == body
    assert db.get(TimelineFileReference, (comment.id, 1, file_id)) is not None
    assert db.get(TimelineRevision, (comment.id, 2)).kind == "withdraw"
    assert db.get(TimelineEntry, original.id).event_data["summary"] == "old event"
    assert import_timeline(db)[0]["already_imported"] == 2
    assert db.scalar(select(func.count()).select_from(TimelineEntry)) == 2
    assert db.scalar(select(func.count()).select_from(TimelineFileReference)) == 1


def test_import_wiki_preserves_independent_versions_links_and_frontmatter_samples(db, world):
    pid = world["project"].id
    actor = world["admin"].id
    raw = "---\nsummary: from yaml\ntags: [tested]\n---\n[[old-name#Heading|Visible]]\n\n```yaml\n---\n[[old-name]]\n```\n\n`[[old-name]]`"
    target = Document(project_id=pid, code="TERM-1", doc_type="wiki", title="Target", doc_metadata={"aliases": ["old-name"]})
    document = Document(project_id=pid, code="DOC-1", doc_type="wiki", title="Current", parent_id="TERM-1",
                        content=raw, doc_metadata={"summary": "older", "doc_kind": "custom-category"}, created_by=actor)
    db.add(target)
    db.flush()
    db.add(document)
    db.flush()
    old = DocumentVersion(project_id=pid, document_id="DOC-1", title="Older", version_no=2,
                          content="[[TERM-1]]", created_by=actor)
    current = DocumentVersion(project_id=pid, document_id="DOC-1", title="Current", version_no=3,
                              content=raw, doc_metadata=document.doc_metadata, created_by=actor)
    db.add_all([old, current])
    db.commit()

    counts, _ = import_wiki(db)
    assert counts == {"documents_imported": 2, "versions_imported": 3}
    live = db.get(Wiki, (pid, "DOC-1"))
    assert (live.summary, live.category, live.tags) == ("from yaml", "custom-category", ["tested"])
    assert (live.version_no, live.parent_id, live.updated_at) == (3, "TERM-1", document.updated_at)
    assert f"[Visible](</projects/{pid}/wiki/TERM-1#Heading>)" in live.body
    assert live.body.count("[[old-name]]") == 2
    assert db.get(WikiVersion, old.id).created_by == actor
    assert db.get(WikiVersion, current.id).body == live.body
    assert db.scalar(select(func.count()).select_from(WikiReference)) == 2
    assert document.content == raw
    assert import_wiki(db)[0] == {"already_imported": 2}


def test_structured_wiki_http_roundtrip_and_stale_version(client, db, world):
    pid = world["project"].id
    login(client, "admin", "admin-pass-1")
    collection = f"/api/v2/projects/{pid}/wiki"
    created = client.post(collection, json={"request_id": str(world["admin"].id), "title": "Structured",
                                            "body": "old body", "summary": "Summary", "tags": ["v2"]})
    assert created.status_code == 201, created.text
    code = created.json()["id"]
    entry = f"{collection}/{code}"
    assert client.patch(entry, json={"expected_version": 1, "patch": {"body": "new body"}}).json()["version"] == 2
    assert client.patch(entry, json={"expected_version": 1, "patch": {"title": "stale"}}).status_code == 409
    assert client.get(entry).json()["body"] == "new body"
    assert client.get(collection).json()["items"][0]["summary"] == "Summary"
    history = client.get(f"{entry}/versions", params={"limit": 1}).json()
    assert history["next_before"] == 2
    assert "body" not in history["items"][0]
    assert client.get(f"{entry}/versions/1").json()["body"] == "old body"


def test_wiki_hierarchy_and_recovery_preserve_independent_deletion(client, db, world):
    from uuid import uuid4

    pid = world["project"].id
    login(client, "admin", "admin-pass-1")
    collection = f"/api/v2/projects/{pid}/wiki"

    def create(title, parent_id=None):
        return client.post(collection, json={
            "request_id": str(uuid4()), "title": title, "parent_id": parent_id,
        }).json()["id"]

    parent = create("Parent")
    child = create("Child", parent)
    separate = create("Independent", parent)
    parent_path = f"{collection}/{parent}"
    child_path = f"{collection}/{child}"
    assert client.patch(f"{parent_path}/location", json={
        "expected_version": 1, "parent_id": child,
    }).status_code == 409
    assert client.delete(f"{collection}/{separate}", params={"confirmed_count": 1}).status_code == 200
    assert client.get(f"{parent_path}/delete-impact").json()["affected_count"] == 2
    assert client.delete(parent_path, params={"confirmed_count": 1}).status_code == 409
    assert client.delete(parent_path, params={"confirmed_count": 2}).status_code == 200
    assert client.get(child_path).status_code == 404
    assert client.post(f"{collection}/trash/{separate}/restore").status_code == 409
    assert client.post(f"{collection}/trash/{parent}/restore").status_code == 200
    assert client.get(child_path).status_code == 200
    assert client.get(f"{collection}/{separate}").status_code == 404
