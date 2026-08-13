"""The worker has one fixed Cognee target and preserves failed desired config."""

from app.models import CogneeRestartJob
from app.services import cognee_configuration, cognee_restart_jobs


def test_failed_restart_keeps_configuration_pending(db, world, monkeypatch):
    configuration = cognee_configuration.update(
        db,
        {
            "llm_provider": "custom",
            "llm_model": "test-model",
            "llm_endpoint": None,
            "embedding_provider": "fastembed",
            "embedding_model": "test-embedding",
            "embedding_dimensions": 384,
        },
    )
    assert configuration.pending_restart is True
    job = cognee_restart_jobs.submit(db, world["admin"], confirmed=True)
    assert cognee_restart_jobs.claim_next(db) is not None
    monkeypatch.setattr(cognee_restart_jobs, "_write_runtime_environment", lambda _: None)
    monkeypatch.setattr(cognee_restart_jobs, "_recreate_cognee", lambda: (_ for _ in ()).throw(RuntimeError("docker unavailable")))

    completed = cognee_restart_jobs.execute(db, job_id=next(iter(db.query(CogneeRestartJob))).id)
    assert completed["status"] == "failed"
    assert completed["error"] == "docker unavailable"
    assert cognee_configuration.get_or_create(db).pending_restart is True


def test_successful_restart_clears_pending_flag(db, world, monkeypatch):
    cognee_configuration.update(
        db,
        {
            "llm_provider": "custom",
            "llm_model": "test-model",
            "llm_endpoint": None,
            "embedding_provider": "fastembed",
            "embedding_model": "test-embedding",
            "embedding_dimensions": 384,
        },
    )
    job = cognee_restart_jobs.submit(db, world["admin"], confirmed=True)
    assert cognee_restart_jobs.claim_next(db) is not None
    monkeypatch.setattr(cognee_restart_jobs, "_write_runtime_environment", lambda _: None)
    monkeypatch.setattr(cognee_restart_jobs, "_recreate_cognee", lambda: None)

    assert cognee_restart_jobs.execute(db, next(iter(db.query(CogneeRestartJob))).id)["status"] == "completed"
    assert cognee_configuration.get_or_create(db).pending_restart is False


def test_runtime_env_omits_empty_managed_key_for_deployment_fallback(db, world, monkeypatch, tmp_path):
    configuration = cognee_configuration.update(
        db,
        {
            "llm_provider": "custom",
            "llm_model": "test-model",
            "llm_endpoint": None,
            "embedding_provider": "fastembed",
            "embedding_model": "test-embedding",
            "embedding_dimensions": 384,
        },
    )
    monkeypatch.setattr(cognee_restart_jobs, "_env_file_path", lambda: tmp_path / "cognee-runtime.env")
    cognee_restart_jobs._write_runtime_environment(configuration)
    content = (tmp_path / "cognee-runtime.env").read_text(encoding="utf-8")
    assert "LLM_API_KEY=" not in content
