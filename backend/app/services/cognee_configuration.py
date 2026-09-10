"""Persistent configuration and observable runtime status for Cognee."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import CogneeConfiguration, CogneeRestartJob, Team
from ..schemas import validate_llm_model
from ..security import decrypt_secret, encrypt_secret


def _workspace_team(db: Session) -> Team:
    """Return the single workspace team created during bootstrap."""
    return db.scalar(select(Team).order_by(Team.created_at).limit(1))


def _default_configuration(team_id) -> CogneeConfiguration:
    settings = get_settings()
    return CogneeConfiguration(
        team_id=team_id,
        llm_provider=settings.cognee_llm_provider,
        llm_model=settings.cognee_llm_model,
        llm_endpoint=settings.cognee_llm_endpoint,
        embedding_provider=settings.cognee_embedding_provider,
        embedding_model=settings.cognee_embedding_model,
        embedding_dimensions=settings.cognee_embedding_dimensions,
    )


def get_or_create(db: Session) -> CogneeConfiguration:
    team = _workspace_team(db)
    row = db.scalar(select(CogneeConfiguration).where(CogneeConfiguration.team_id == team.id))
    if row is None:
        row = _default_configuration(team.id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update(db: Session, values: dict) -> CogneeConfiguration:
    row = get_or_create(db)
    # 防御性校验(REQ bc36ae8b):HTTP 入口已由 schemas.CogneeConfigurationUpdate
    # 拦截,这里覆盖不经 schema 的程序化调用方,并把净值写回以免存入首尾空白。
    values["llm_model"] = validate_llm_model(values.get("llm_model", ""))
    for field in (
        "llm_provider",
        "llm_model",
        "llm_endpoint",
        "embedding_provider",
        "embedding_model",
        "embedding_dimensions",
    ):
        setattr(row, field, values[field])
    if "llm_api_key" in values:
        key = values["llm_api_key"]
        row.llm_api_key_encrypted = encrypt_secret(key) if key else None
    row.pending_restart = True
    db.commit()
    db.refresh(row)
    return row


def payload(row: CogneeConfiguration) -> dict:
    if row.llm_api_key_encrypted:
        key = decrypt_secret(row.llm_api_key_encrypted)
        key_display = mask_api_key(key)
        key_source = "managed"
    else:
        key = deployment_api_key()
        key_display = mask_api_key(key) if key else None
        key_source = "deployment" if key else "unconfigured"
    return {
        "llm_provider": row.llm_provider,
        "llm_model": row.llm_model,
        "llm_endpoint": row.llm_endpoint,
        "llm_api_key_configured": row.llm_api_key_encrypted is not None,
        "llm_api_key_display": key_display,
        "llm_api_key_source": key_source,
        "embedding_provider": row.embedding_provider,
        "embedding_model": row.embedding_model,
        "embedding_dimensions": row.embedding_dimensions,
        "pending_restart": row.pending_restart,
        "updated_at": row.updated_at.isoformat(),
    }


def mask_api_key(key: str) -> str:
    """Keep a recognizable prefix/suffix while never returning the secret."""
    if len(key) <= 7:
        return "*" * len(key)
    return f"{key[:3]}{'*' * max(8, len(key) - 7)}{key[-4:]}"


def deployment_api_key() -> str | None:
    """Read the Compose key solely for a masked display to workspace admins."""
    path = get_settings().cognee_deployment_env_file.resolve()
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                value = line.removeprefix("DEEPSEEK_API_KEY=").strip()
                return value or None
    except OSError:
        return None
    return None


def probe_runtime() -> dict:
    """Return a short, non-authenticated reachability probe for Cognee.

    Cognee's root/docs endpoints are sufficient to distinguish an unavailable
    service from a reachable one without performing a memory operation.
    """
    settings = get_settings()
    checked_at = datetime.now(timezone.utc).isoformat()
    endpoint = settings.cognee_base_url.removesuffix("/api/v1") + "/docs"
    try:
        with urlopen(endpoint, timeout=min(settings.cognee_timeout_seconds, 3.0)) as response:
            if 200 <= response.status < 500:
                return {"availability": "reachable", "detail": None, "checked_at": checked_at}
    except HTTPError as exc:
        # Any HTTP response proves the service process is reachable.  Its own
        # access policy may deny the requested documentation endpoint.
        if exc.code < 500:
            return {"availability": "reachable", "detail": None, "checked_at": checked_at}
        return {"availability": "unreachable", "detail": f"Cognee 返回 HTTP {exc.code}", "checked_at": checked_at}
    except (URLError, TimeoutError, OSError):
        return {"availability": "unreachable", "detail": "无法连接 Cognee 服务", "checked_at": checked_at}
    return {"availability": "unreachable", "detail": "Cognee 健康检查未返回成功响应", "checked_at": checked_at}


def runtime_status(db: Session) -> dict:
    team = _workspace_team(db)
    latest_restart = db.scalar(
        select(CogneeRestartJob)
        .where(CogneeRestartJob.team_id == team.id)
        .order_by(CogneeRestartJob.created_at.desc())
        .limit(1)
    )
    restart_payload = None
    if latest_restart is not None:
        from .cognee_restart_jobs import RESTART_JOB_LABELS

        restart_payload = {
            "status": latest_restart.status,
            "status_label": RESTART_JOB_LABELS[latest_restart.status],
            "error": latest_restart.error,
            "requested_at": latest_restart.created_at.isoformat(),
            "finished_at": latest_restart.finished_at.isoformat() if latest_restart.finished_at else None,
        }
    return {"runtime": probe_runtime(), "latest_restart": restart_payload}
