"""记忆蒸馏任务队列的补边测试(规格书 §6 记忆闭环)。"""

import uuid

import pytest

from app.errors import AppError
from app.models import MemoryImproveJob
from app.services import memory as memory_svc
from app.services import memory_improve_jobs as svc


class FakeCognee:
    def create_dataset(self, name):
        return "dataset-1"

    def list_sessions(self, dataset_id):
        return []

    def delete_session(self, session_id):
        pass

    def delete_dataset(self, dataset_id):
        pass


def provision(db, world) -> FakeCognee:
    client = FakeCognee()
    memory_svc.provision_project(db, world["project"].id, client)
    db.commit()
    return client


def test_submit_requires_session_id(db, world):
    provision(db, world)
    with pytest.raises(AppError) as e:
        svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "  ")
    assert e.value.code == "conflict"


def test_submit_rejects_non_member_agent(db, world):
    provision(db, world)
    with pytest.raises(AppError) as e:
        svc.submit(db, world["admin"], world["project"].id, uuid.uuid4(), "s")
    assert e.value.code == "not_found"
    assert "目标 agent" in e.value.message


def test_submit_fails_fast_without_provisioned_dataset(db, world):
    with pytest.raises(AppError) as e:
        svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    assert e.value.code == "not_found"


def test_get_scopes_jobs_to_project(db, world):
    provision(db, world)
    job = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    assert svc.get(db, world["admin"], world["project"].id, uuid.UUID(job["id"]))["status"] == "queued"
    with pytest.raises(AppError) as e:
        svc.get(db, world["admin"], world["project"].id, uuid.uuid4())
    assert e.value.code == "not_found"


def test_claim_next_returns_none_when_empty(db, world):
    assert svc.claim_next(db) is None


def test_execute_requires_existing_job(db, world):
    with pytest.raises(AppError) as e:
        svc.execute(db, uuid.uuid4(), FakeCognee())
    assert e.value.code == "not_found"


def test_execute_leaves_non_running_job_untouched(db, world):
    provision(db, world)
    job = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    result = svc.execute(db, uuid.UUID(job["id"]), FakeCognee())
    assert result["status"] == "queued"


def test_execute_fails_when_requester_was_deleted(db, world):
    provision(db, world)
    job = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    db.delete(world["admin"])
    db.commit()

    svc.claim_next(db)
    result = svc.execute(db, uuid.UUID(job["id"]), FakeCognee())

    assert result["status"] == "failed"
    assert result["error"] == "提交者不存在"


def test_recover_interrupted_jobs_marks_them_unknown(db, world):
    provision(db, world)
    submitted = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    svc.claim_next(db)
    assert svc.recover_interrupted_jobs(db) == 1
    job = db.get(MemoryImproveJob, uuid.UUID(submitted["id"]))
    assert job.status == "unknown"
    assert "未自动重试" in job.error


def test_concurrent_duplicate_submit_resolves_to_same_job(db, world):
    provision(db, world)
    first = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    second = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")
    assert second["id"] == first["id"]


def test_submit_integrity_error_race_falls_back_to_active_job(db, world, monkeypatch):
    """模拟并发竞态:预检漏看已存在的活跃任务,insert 触发唯一索引冲突后回查。"""
    provision(db, world)
    svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")

    real_scalar = db.scalar
    state = {"race": True}

    def fake_scalar(stmt, *args, **kwargs):
        if state["race"] and "memory_improve_job" in str(stmt):
            state["race"] = False
            return None
        return real_scalar(stmt, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", fake_scalar)
    result = svc.submit(db, world["admin"], world["project"].id, world["agent"].id, "s")

    assert result["status"] == "queued"
    assert db.query(MemoryImproveJob).count() == 1
