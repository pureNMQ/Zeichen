import uuid

import pytest

from app.errors import AppError
from app.models import Activity, Project, ProjectMember
from app.services import memory
from app.services import memory_improve_jobs


class FakeCognee:
    def __init__(self):
        self.calls = []
        self.sessions = []

    def create_dataset(self, name): self.calls.append(("create_dataset", name)); return "dataset-1"
    def remember(self, **kwargs): self.calls.append(("remember", kwargs)); self.sessions.append({"id": kwargs["session_id"]}); return {"data_id": "data-1"}
    def recall(self, **kwargs): self.calls.append(("recall", kwargs)); return {"items": []}
    def improve(self, **kwargs): self.calls.append(("improve", kwargs)); return {"ok": True}
    def forget(self, **kwargs): self.calls.append(("forget", kwargs)); return {"ok": True}
    def list_data(self, dataset_id): self.calls.append(("list_data", dataset_id)); return [{"id": "data-1", "external_metadata": {"source_id": "source-a"}}]
    def get_data_raw(self, dataset_id, data_id): self.calls.append(("get_data_raw", dataset_id, data_id)); return ""
    def list_sessions(self, dataset_id): self.calls.append(("list_sessions", dataset_id)); return self.sessions
    def get_session(self, session_id):
        self.calls.append(("get_session", session_id))
        return {
            "session_id": session_id,
            "effective_status": "running",
            "qas": [{"time": "2026-08-07T02:11:28Z", "question": "What is the release code?", "answer": "jade-orbit-42"}],
            "traces": [],
        }
    def delete_session(self, session_id): self.calls.append(("delete_session", session_id))
    def delete_dataset(self, dataset_id): self.calls.append(("delete_dataset", dataset_id))


def test_remember_namespaces_session_and_records_source(db, world):
    client = FakeCognee()
    result = memory.remember(db, world["agent"], world["project"].id, "work-42", "note", {"entity_type": "task", "entity_id": "a"}, client)
    assert result["data_id"] == "data-1"
    call = next(payload for name, payload in client.calls if name == "remember")
    assert call["dataset_name"] == f"zeichen:{world['project'].id}"
    assert call["session_id"] == f"zeichen:{world['project'].id}:{world['agent'].id}:work-42"
    assert call["metadata"]["source_id"] == str(world["agent"].id)
    assert call["metadata"]["entity_type"] == "task"


def test_viewer_can_recall_but_cannot_write_or_create_space(db, world):
    client = FakeCognee()
    # A viewer cannot provision a memory space, but can read a space created
    # by a project editor.
    with pytest.raises(AppError) as error:
        memory.recall(db, world["member"], world["project"].id, "query", client=client)
    assert error.value.code == "not_found"
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    assert memory.recall(db, world["member"], world["project"].id, "query", client=client)["items"] == []
    with pytest.raises(AppError) as error:
        memory.remember(db, world["member"], world["project"].id, "s", "note", client=client)
    assert error.value.code == "permission_denied"


def test_editor_opening_legacy_project_memory_provisions_space(db, world):
    client = FakeCognee()

    memory.list_memory(db, world["agent"], world["project"].id, client=client)
    assert ("create_dataset", f"zeichen:{world['project'].id}") in client.calls
    assert ("list_data", "dataset-1") in client.calls


def test_list_memory_hydrates_cognee_data_into_a_displayable_memory_card(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "release", "note", client=client)
    client.list_data = lambda dataset_id: [{
        "id": "data-1",
        "createdAt": "2026-08-07T02:13:17Z",
        "name": "session-learning.txt",
    }]
    client.get_data_raw = lambda dataset_id, data_id: (
        f"# Session learning — 2026-08-07 (session zeichen:{world['project'].id}:{world['agent'].id}:release)\n\n"
        "The green release passphrase is jade-orbit-42."
    )

    result = memory.list_memory(db, world["admin"], world["project"].id, client=client)

    assert result == {"items": [{
        "id": "data-1",
        "content": "The green release passphrase is jade-orbit-42.",
        "created_at": "2026-08-07T02:13:17Z",
        "external_metadata": {
            "source_id": str(world["agent"].id),
            "source_name": world["agent"].username,
            "source_kind": "agent",
        },
    }]}


def test_list_memory_extracts_the_original_answer_from_session_transcript(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "release", "note", client=client)
    client.list_data = lambda dataset_id: [{"id": "data-1"}]
    client.get_data_raw = lambda dataset_id, data_id: (
        f"Session ID: zeichen:{world['project'].id}:{world['agent'].id}:release\n\n"
        "Question: Project memory submitted by agent-a\n\n"
        "Answer: The green release passphrase is jade-orbit-42.\n\n"
        "Question: What is the passphrase?\n\n"
        "Answer: jade-orbit-42."
    )

    result = memory.list_memory(db, world["admin"], world["project"].id, client=client)

    assert result["items"][0]["content"] == "The green release passphrase is jade-orbit-42."
    assert result["items"][0]["external_metadata"]["source_name"] == world["agent"].username


def test_improve_targets_only_selected_project_agent(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    assert memory.improve(db, world["admin"], world["project"].id, world["agent"].id, "s", client)["ok"]
    assert (
        "improve",
        {
            "dataset_id": "dataset-1",
            "session_id": f"zeichen:{world['project'].id}:{world['agent'].id}:s",
        },
    ) in client.calls
    with pytest.raises(AppError) as error:
        memory.improve(db, world["admin"], world["project"].id, uuid.uuid4(), "s", client)
    assert error.value.code == "not_found"


def test_improve_in_progress_is_a_conflict_and_does_not_record_success_activity(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    client.improve = lambda **kwargs: {}

    with pytest.raises(AppError) as error:
        memory.improve(db, world["admin"], world["project"].id, world["agent"].id, "s", client)

    assert error.value.code == "conflict"
    assert "正在蒸馏中" in error.value.message
    assert not db.query(Activity).filter(Activity.action == "memory_improve").count()


def test_submit_improve_job_is_deduplicated_for_the_same_session(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)

    first = memory_improve_jobs.submit(
        db, world["admin"], world["project"].id, world["agent"].id, "s"
    )
    second = memory_improve_jobs.submit(
        db, world["admin"], world["project"].id, world["agent"].id, "s"
    )

    assert first["status"] == "queued"
    assert second["id"] == first["id"]
    assert not [call for call in client.calls if call[0] == "improve"]


def test_improve_worker_completes_a_queued_job_and_records_activity(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    submitted = memory_improve_jobs.submit(
        db, world["admin"], world["project"].id, world["agent"].id, "s"
    )

    assert memory_improve_jobs.claim_next(db) == uuid.UUID(submitted["id"])
    completed = memory_improve_jobs.execute(db, uuid.UUID(submitted["id"]), client)

    assert completed["status"] == "completed"
    assert completed["result"] == {"ok": True}
    assert db.query(Activity).filter(Activity.action == "memory_improve").count() == 1


def test_improve_worker_marks_cognee_skip_as_upstream_busy(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    submitted = memory_improve_jobs.submit(
        db, world["admin"], world["project"].id, world["agent"].id, "s"
    )
    client.improve = lambda **kwargs: {}

    memory_improve_jobs.claim_next(db)
    result = memory_improve_jobs.execute(db, uuid.UUID(submitted["id"]), client)

    assert result["status"] == "upstream_busy"
    assert result["error"] == "该会话正在蒸馏中，请稍后再试"
    assert not db.query(Activity).filter(Activity.action == "memory_improve").count()


def test_improve_worker_marks_a_client_timeout_without_retrying(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    submitted = memory_improve_jobs.submit(
        db, world["admin"], world["project"].id, world["agent"].id, "s"
    )
    def timeout(**kwargs):
        client.calls.append(("improve", kwargs))
        raise TimeoutError("cognee 请求超时")

    client.improve = timeout

    memory_improve_jobs.claim_next(db)
    result = memory_improve_jobs.execute(db, uuid.UUID(submitted["id"]), client)

    assert result["status"] == "timed_out"
    assert "未自动重试" in result["error"]
    assert len([call for call in client.calls if call[0] == "improve"]) == 1
    assert not db.query(Activity).filter(Activity.action == "memory_improve").count()


def test_session_detail_is_scoped_to_project_and_exposes_cached_qas(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "release", "note", client=client)
    raw = f"zeichen:{world['project'].id}:{world['agent'].id}:release"

    detail = memory.get_session_detail(db, world["admin"], world["project"].id, raw, client)

    assert detail == {
        "session_id": raw,
        "business_session_id": "release",
        "source_id": str(world["agent"].id),
        "source_name": world["agent"].username,
        "source_kind": "agent",
        "status": "running",
        "qas": [{"time": "2026-08-07T02:11:28Z", "question": "What is the release code?", "answer": "jade-orbit-42"}],
        "traces": [],
    }


def test_list_sessions_includes_a_preview_of_the_latest_cached_qa(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "release", "note", client=client)

    result = memory.list_sessions(db, world["admin"], world["project"].id, client)

    assert result[0]["preview"] == "What is the release code? · jade-orbit-42"


def test_project_purge_deletes_sessions_before_dataset(db, world):
    client = FakeCognee()
    memory.remember(db, world["agent"], world["project"].id, "s", "note", client=client)
    memory.purge_project(db, world["project"].id, client)
    names = [name for name, _ in client.calls]
    assert names.index("delete_session") < names.index("delete_dataset")
