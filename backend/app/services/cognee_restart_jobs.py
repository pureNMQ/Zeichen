"""Queue and execute fixed-target Cognee restarts without shell interpolation."""

import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import conflict, invalid_request, not_found
from ..models import CogneeConfiguration, CogneeRestartJob, Team, User
from ..security import decrypt_secret
from . import cognee_configuration


ACTIVE_STATUSES = ("queued", "running")
RESTART_JOB_LABELS = {
    "queued": "排队中（等待重启 worker）",
    "running": "运行中",
    "completed": "已完成",
    "failed": "失败",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _team(db: Session) -> Team:
    return db.scalar(select(Team).order_by(Team.created_at).limit(1))


def _payload(job: CogneeRestartJob) -> dict:
    return {
        "id": str(job.id),
        "status": job.status,
        "status_label": RESTART_JOB_LABELS[job.status],
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def submit(db: Session, actor: User, confirmed: bool) -> dict:
    if not confirmed:
        raise invalid_request("必须确认 Cognee 重启期间记忆功能不可用")
    team = _team(db)
    active = db.scalar(
        select(CogneeRestartJob)
        .where(CogneeRestartJob.team_id == team.id, CogneeRestartJob.status.in_(ACTIVE_STATUSES))
        .order_by(CogneeRestartJob.created_at.desc())
    )
    if active is not None:
        return _payload(active)
    job = CogneeRestartJob(team_id=team.id, requested_by_id=actor.id, status="queued")
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        active = db.scalar(
            select(CogneeRestartJob)
            .where(CogneeRestartJob.team_id == team.id, CogneeRestartJob.status.in_(ACTIVE_STATUSES))
            .order_by(CogneeRestartJob.created_at.desc())
        )
        if active is None:
            raise
        return _payload(active)
    db.refresh(job)
    return _payload(job)


def get(db: Session, job_id: uuid.UUID) -> dict:
    job = db.get(CogneeRestartJob, job_id)
    if job is None or job.team_id != _team(db).id:
        raise not_found("Cognee 重启任务不存在")
    return _payload(job)


def claim_next(db: Session) -> uuid.UUID | None:
    job = db.scalar(
        select(CogneeRestartJob)
        .where(CogneeRestartJob.status == "queued")
        .order_by(CogneeRestartJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "running"
    job.started_at = _now()
    db.commit()
    return job.id


def _env_file_path() -> Path:
    settings = get_settings()
    path = settings.cognee_runtime_env_file.resolve()
    runtime_root = path.parent.resolve()
    if runtime_root.name != ".scratch":
        raise RuntimeError("Cognee 运行时配置文件必须位于 .scratch 目录")
    return path


def _write_runtime_environment(configuration: CogneeConfiguration) -> None:
    path = _env_file_path()
    secret = (
        decrypt_secret(configuration.llm_api_key_encrypted)
        if configuration.llm_api_key_encrypted
        else ""
    )
    # Docker's env-file format has no escaping contract for multiline values;
    # reject them instead of producing a subtly different runtime configuration.
    values = {
        "LLM_PROVIDER": configuration.llm_provider,
        "LLM_MODEL": configuration.llm_model,
        "LLM_ENDPOINT": configuration.llm_endpoint or "",
        "EMBEDDING_PROVIDER": configuration.embedding_provider,
        "EMBEDDING_MODEL": configuration.embedding_model,
        "EMBEDDING_DIMENSIONS": str(configuration.embedding_dimensions or ""),
    }
    # Omitting a managed key intentionally leaves the deployment's base .env
    # fallback in place.  Writing LLM_API_KEY= would suppress that fallback.
    if secret:
        values["LLM_API_KEY"] = secret
    if any("\n" in value or "\r" in value for value in values.values()):
        raise invalid_request("Cognee 配置值不能包含换行符")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows and some mounted filesystems do not support POSIX mode bits.
        pass


class DockerComposeRestartChannel:
    """Minimal-privilege docker.sock execution channel.

    It exposes exactly one operation: recreating the fixed ``cognee`` service
    with a server-owned, constant ``docker compose`` argv.  It never accepts a
    command, service, or path from clients, never runs another docker
    subcommand, and never interpolates a shell.
    """

    def recreate_cognee(self, *, runtime_env_file: Path, project_dir: Path) -> None:
        settings = get_settings()
        # A recreate is required: Docker restart does not pick up changed
        # container environment variables.  Every argument is server-owned and
        # constant; the runtime env file and project directory come from the
        # caller (the worker passes deployment settings), never from a request.
        completed = subprocess.run(
            [
                settings.cognee_compose_executable,
                "compose",
                "--env-file",
                ".env",
                "--env-file",
                str(runtime_env_file),
                "up",
                "-d",
                "--force-recreate",
                "cognee",
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=settings.cognee_restart_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Docker Compose 执行失败").strip()
            raise RuntimeError(detail[:2000])


def get_docker_channel() -> DockerComposeRestartChannel:
    """Injection point: workers and tests may substitute a fake channel."""
    return DockerComposeRestartChannel()


def _recreate_cognee() -> None:
    get_docker_channel().recreate_cognee(
        runtime_env_file=_env_file_path(),
        project_dir=get_settings().cognee_compose_project_dir,
    )


def execute(db: Session, job_id: uuid.UUID) -> dict:
    job = db.get(CogneeRestartJob, job_id)
    if job is None:
        raise not_found("Cognee 重启任务不存在")
    if job.status != "running":
        return _payload(job)
    try:
        configuration = cognee_configuration.get_or_create(db)
        _write_runtime_environment(configuration)
        _recreate_cognee()
        configuration.pending_restart = False
        job.status = "completed"
    except Exception as exc:  # Keep the desired configuration pending on every failure.
        job.status = "failed"
        job.error = str(exc)[:2000]
    finally:
        job.finished_at = _now()
        db.commit()
    return _payload(job)


def recover_interrupted_jobs(db: Session) -> int:
    jobs = db.scalars(select(CogneeRestartJob).where(CogneeRestartJob.status == "running")).all()
    for job in jobs:
        job.status = "failed"
        job.error = "重启 worker 已中断；Cognee 的实际运行状态未知，请检查健康状态后重试"
        job.finished_at = _now()
    if jobs:
        db.commit()
    return len(jobs)
