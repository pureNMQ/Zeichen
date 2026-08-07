"""Persistent queue and worker operations for long-running session distillation."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import AppError, conflict, not_found
from ..models import MemoryImproveJob, ProjectMember, User
from . import memory
from .cognee import CogneeClient
from .permissions import get_accessible_project, require_project_role


ACTIVE_STATUSES = ("queued", "running")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_dict(job: MemoryImproveJob) -> dict:
    return {
        "id": str(job.id),
        "project_id": str(job.project_id),
        "agent_id": str(job.target_agent_id),
        "session_id": job.session_id,
        "status": job.status,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "heartbeat_at": job.heartbeat_at,
        "finished_at": job.finished_at,
    }


def _validate_target(db: Session, project_id: uuid.UUID, target_agent_id: uuid.UUID) -> User:
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target_agent_id,
        )
    )
    target = db.get(User, target_agent_id)
    if member is None or target is None or not target.is_agent:
        raise not_found("目标 agent 不在项目中")
    return target


def submit(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    target_agent_id: uuid.UUID,
    session_id: str,
) -> dict:
    """Enqueue a job, returning an already-active job for the same session."""
    require_project_role(db, actor.id, project_id, "editor")
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise conflict("session_id 不能为空")
    _validate_target(db, project_id, target_agent_id)
    # Fail fast for projects without a provisioned Cognee dataset; the worker
    # must never create resources on behalf of a timed-out MCP request.
    memory._dataset(db, project_id, CogneeClient(), create=False)

    active = db.scalar(
        select(MemoryImproveJob)
        .where(
            MemoryImproveJob.project_id == project_id,
            MemoryImproveJob.target_agent_id == target_agent_id,
            MemoryImproveJob.session_id == normalized_session_id,
            MemoryImproveJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(MemoryImproveJob.created_at.desc())
    )
    if active is not None:
        return _job_dict(active)

    job = MemoryImproveJob(
        project_id=project_id,
        target_agent_id=target_agent_id,
        requested_by_id=actor.id,
        session_id=normalized_session_id,
        status="queued",
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        # The database partial unique index resolves a concurrent submitter to
        # the same active job instead of allowing duplicate Cognee work.
        db.rollback()
        active = db.scalar(
            select(MemoryImproveJob)
            .where(
                MemoryImproveJob.project_id == project_id,
                MemoryImproveJob.target_agent_id == target_agent_id,
                MemoryImproveJob.session_id == normalized_session_id,
                MemoryImproveJob.status.in_(ACTIVE_STATUSES),
            )
            .order_by(MemoryImproveJob.created_at.desc())
        )
        if active is None:
            raise
        return _job_dict(active)
    db.refresh(job)
    return _job_dict(job)


def get(db: Session, actor: User, project_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    require_project_role(db, actor.id, project_id, "editor")
    job = db.get(MemoryImproveJob, job_id)
    if job is None or job.project_id != project_id:
        raise not_found("蒸馏任务不存在")
    return _job_dict(job)


def claim_next(db: Session) -> uuid.UUID | None:
    """Claim exactly one queued job. PostgreSQL skips claims held by another worker."""
    job = db.scalar(
        select(MemoryImproveJob)
        .where(MemoryImproveJob.status == "queued")
        .order_by(MemoryImproveJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = "running"
    job.started_at = job.heartbeat_at = _now()
    db.commit()
    return job.id


def _json_safe(value: object) -> dict | list:
    return json.loads(json.dumps(value, default=str))


def execute(db: Session, job_id: uuid.UUID, client: CogneeClient | None = None) -> dict:
    """Run a claimed job once. Never retry automatically after an uncertain outcome."""
    job = db.get(MemoryImproveJob, job_id)
    if job is None:
        raise not_found("蒸馏任务不存在")
    if job.status != "running":
        return _job_dict(job)

    requester = db.get(User, job.requested_by_id)
    if requester is None:
        job.status, job.error, job.finished_at = "failed", "提交者不存在", _now()
        db.commit()
        return _job_dict(job)

    settings = get_settings()
    client = client or CogneeClient(timeout=settings.cognee_improve_job_timeout_seconds)
    try:
        result = memory.improve(
            db,
            requester,
            job.project_id,
            job.target_agent_id,
            job.session_id,
            client,
        )
        job.status = "completed"
        job.result = _json_safe(result)
    except AppError as exc:
        # Cognee returns {} when a server-side stale lock already exists. It
        # is not this job's successful completion and cannot be auto-retried.
        job.status = "upstream_busy" if exc.code == "conflict" else "failed"
        job.error = exc.message
    except TimeoutError:
        job.status = "timed_out"
        job.error = "等待 Cognee 超过任务时限；远端执行状态未知，未自动重试"
    except Exception as exc:  # pragma: no cover - provider-specific failures
        job.status = "failed"
        job.error = str(exc)[:2000]
    finally:
        job.heartbeat_at = job.finished_at = _now()
        db.commit()
    return _job_dict(job)


def recover_interrupted_jobs(db: Session) -> int:
    """Do not replay a job whose worker died while Cognee may still run it."""
    jobs = db.scalars(select(MemoryImproveJob).where(MemoryImproveJob.status == "running")).all()
    for job in jobs:
        job.status = "unknown"
        job.error = "执行 worker 已重启；Cognee 远端执行状态未知，未自动重试"
        job.finished_at = job.heartbeat_at = _now()
    if jobs:
        db.commit()
    return len(jobs)
