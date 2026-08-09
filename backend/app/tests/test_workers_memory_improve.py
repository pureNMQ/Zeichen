"""记忆蒸馏 worker 入口冒烟(规格书 §6 记忆闭环的异步执行侧)。"""

import uuid

import pytest

from app.services import memory_improve_jobs as jobs
from app.workers import memory_improve as worker


class FakeSessionLocal:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


def test_run_once_claims_and_executes_a_job(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", FakeSessionLocal)
    calls = []
    job_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    monkeypatch.setattr(jobs, "claim_next", lambda db: job_id)
    monkeypatch.setattr(jobs, "execute", lambda db, jid: calls.append(jid))

    assert worker.run_once() is True
    assert calls == [job_id]


def test_run_once_idles_without_jobs(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(jobs, "claim_next", lambda db: None)
    monkeypatch.setattr(jobs, "execute", lambda db, job_id: pytest.fail("不应执行"))

    assert worker.run_once() is False


def test_run_recovers_interrupted_jobs_then_polls(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", FakeSessionLocal)
    calls = []
    sleeps = []

    monkeypatch.setattr(jobs, "recover_interrupted_jobs", lambda db: calls.append("recover"))
    monkeypatch.setattr(worker, "run_once", lambda: False)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: (sleeps.append(seconds), (_ for _ in ()).throw(SystemExit)))

    with pytest.raises(SystemExit):
        worker.run()

    assert calls == ["recover"]
    assert sleeps, "空闲时应按轮询间隔 sleep"


def test_run_keeps_working_while_jobs_exist(monkeypatch):
    monkeypatch.setattr(worker, "SessionLocal", FakeSessionLocal)
    monkeypatch.setattr(jobs, "recover_interrupted_jobs", lambda db: None)
    state = {"remaining": 3}

    def fake_run_once():
        if state["remaining"] > 0:
            state["remaining"] -= 1
            return True
        return False

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: (_ for _ in ()).throw(SystemExit))

    with pytest.raises(SystemExit):
        worker.run()

    assert state["remaining"] == 0
