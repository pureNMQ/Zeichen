"""Permission-enforcing project memory bridge."""

import uuid
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import MemoryDataset, ProjectMember, User
from .cognee import CogneeClient
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity


_SESSION_AGENT_ID = re.compile(r"(?:\(session |Session ID: )zeichen:[0-9a-f-]{36}:([0-9a-f-]{36}):")
_TRANSCRIPT_ANSWER = re.compile(r"^Answer:\s*(.+?)(?=\n\nQuestion:|\Z)", re.MULTILINE | re.DOTALL)


def _dataset(db: Session, project_id: uuid.UUID, client: CogneeClient, create: bool = True) -> MemoryDataset:
    row = db.scalar(select(MemoryDataset).where(MemoryDataset.project_id == project_id))
    if row is None:
        if not create:
            raise not_found("项目尚未创建记忆空间")
        row = MemoryDataset(project_id=project_id, cognee_dataset_id=client.create_dataset(f"zeichen:{project_id}"))
        db.add(row)
        db.flush()
    return row


def provision_project(db: Session, project_id: uuid.UUID, client: CogneeClient | None = None) -> MemoryDataset:
    """Create the project's persistent Cognee Dataset during project provisioning."""
    return _dataset(db, project_id, client or CogneeClient())


def _session(project_id: uuid.UUID, agent_id: uuid.UUID, session_id: str) -> str:
    value = session_id.strip()
    if not value:
        raise invalid_request("session_id 不能为空")
    return f"zeichen:{project_id}:{agent_id}:{value}"


def _metadata(actor: User, anchor: dict | None) -> dict:
    result = {"source_id": str(actor.id), "source_name": actor.username, "source_kind": "agent" if actor.is_agent else "human"}
    if anchor:
        entity_type, entity_id = anchor.get("entity_type"), anchor.get("entity_id")
        if not entity_type or not entity_id:
            raise invalid_request("锚点必须同时提供 entity_type 和 entity_id")
        result["entity_type"] = entity_type
        result["entity_id"] = str(entity_id)
    return result


def _session_parts(project_id: uuid.UUID, session_id: str) -> tuple[uuid.UUID, str] | None:
    prefix = f"zeichen:{project_id}:"
    if not session_id.startswith(prefix):
        return None
    try:
        agent_id_text, business_session_id = session_id[len(prefix):].split(":", 1)
        return uuid.UUID(agent_id_text), business_session_id
    except (ValueError, AttributeError):
        return None


def _session_preview(client: CogneeClient, session_id: str) -> str | None:
    """Return a compact, human-readable preview of the latest cached Q&A."""
    detail = client.get_session(session_id)
    qas = detail.get("qas", []) if isinstance(detail, dict) else []
    if not qas or not isinstance(qas[-1], dict):
        return None
    latest = qas[-1]
    question = " ".join(str(latest.get("question") or "").split())
    answer = " ".join(str(latest.get("answer") or "").split())
    if question and answer:
        return f"{question} · {answer}"
    return question or answer or None


def _session_summary(db: Session, project_id: uuid.UUID, item: Any, client: CogneeClient) -> dict | None:
    raw = str(item.get("session_id") or item.get("id") or "") if isinstance(item, dict) else str(item)
    parsed = _session_parts(project_id, raw)
    if parsed is None:
        return None
    agent_id, business_session_id = parsed
    source = db.get(User, agent_id)
    result = dict(item) if isinstance(item, dict) else {"session_id": raw}
    result.update({"session_id": raw, "business_session_id": business_session_id, "source_id": str(agent_id)})
    if source:
        result.update({"source_name": source.username, "source_kind": "agent" if source.is_agent else "human"})
    preview = _session_preview(client, raw)
    if preview:
        result["preview"] = preview
    return result


def _activity(db: Session, project_id: uuid.UUID, actor: User, action: str, summary: str) -> None:
    record_activity(db, project_id, actor.id, "project", project_id, action, summary)


def _display_memory_item(db: Session, client: CogneeClient, dataset_id: str, item: dict) -> dict:
    """Turn Cognee's file metadata into a safe, human-readable memory card."""
    raw = client.get_data_raw(dataset_id, str(item["id"]))
    heading, separator, body = raw.partition("\n\n")
    if heading.startswith("# Session learning") and separator:
        content = body.strip()
    else:
        answers = _TRANSCRIPT_ANSWER.findall(raw)
        content = answers[0].strip() if answers else raw.strip()
    result: dict[str, Any] = {
        "id": str(item["id"]),
        "content": content,
        "created_at": item.get("created_at") or item.get("createdAt"),
    }
    match = _SESSION_AGENT_ID.search(raw)
    if match:
        try:
            source = db.get(User, uuid.UUID(match.group(1)))
        except ValueError:
            source = None
        if source:
            result["external_metadata"] = {
                "source_id": str(source.id),
                "source_name": source.username,
                "source_kind": "agent" if source.is_agent else "human",
            }
    return result


def remember(db: Session, actor: User, project_id: uuid.UUID, session_id: str, content: str, anchor: dict | None = None, client: CogneeClient | None = None) -> Any:
    require_project_role(db, actor.id, project_id, "editor")
    if not content.strip():
        raise invalid_request("记忆内容不能为空")
    client = client or CogneeClient()
    dataset = _dataset(db, project_id, client)
    result = client.remember(
        dataset_name=f"zeichen:{project_id}",
        session_id=_session(project_id, actor.id, session_id),
        content=content,
        metadata=_metadata(actor, anchor),
    )
    _activity(db, project_id, actor, "memory_remember", "写入记忆会话")
    db.commit()
    return result


def recall(db: Session, actor: User, project_id: uuid.UUID, query: str, session_id: str | None = None, client: CogneeClient | None = None) -> Any:
    get_accessible_project(db, actor.id, project_id)
    client = client or CogneeClient()
    dataset = _dataset(db, project_id, client, create=False)
    scoped = _session(project_id, actor.id, session_id) if session_id else None
    return client.recall(dataset_id=dataset.cognee_dataset_id, query=query, session_id=scoped)


def improve(db: Session, actor: User, project_id: uuid.UUID, target_agent_id: uuid.UUID, session_id: str, client: CogneeClient | None = None) -> Any:
    require_project_role(db, actor.id, project_id, "editor")
    member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == target_agent_id))
    target = db.get(User, target_agent_id)
    if member is None or target is None or not target.is_agent:
        raise not_found("目标 agent 不在项目中")
    client = client or CogneeClient()
    dataset = _dataset(db, project_id, client, create=False)
    result = client.improve(
        dataset_id=dataset.cognee_dataset_id,
        session_id=_session(project_id, target_agent_id, session_id),
    )
    # Cognee 1.4.1 returns an empty object when the per-session improve lock
    # is already held.  That is an in-progress conflict, never a successful
    # distillation: recording an activity here would falsely report success.
    if result == {}:
        raise conflict("该会话正在蒸馏中，请稍后再试")
    _activity(db, project_id, actor, "memory_improve", f"蒸馏 agent 会话 {session_id}")
    db.commit()
    return result


def list_memory(db: Session, actor: User, project_id: uuid.UUID, source_id: uuid.UUID | None = None, client: CogneeClient | None = None) -> Any:
    get_accessible_project(db, actor.id, project_id)
    client = client or CogneeClient()
    dataset = db.scalar(select(MemoryDataset).where(MemoryDataset.project_id == project_id))
    if dataset is None:
        # Backfill pre-provisioning projects when an editor first opens their
        # memory page. Viewers retain read-only access and cannot create it.
        require_project_role(db, actor.id, project_id, "editor")
        dataset = provision_project(db, project_id, client)
        db.commit()
    result = client.list_data(dataset.cognee_dataset_id)
    entries = result.get("items", result) if isinstance(result, dict) else result
    if isinstance(entries, list):
        entries = [
            _display_memory_item(db, client, dataset.cognee_dataset_id, item)
            for item in entries
            if isinstance(item, dict) and item.get("id")
        ]
    if source_id and isinstance(entries, list):
        entries = [item for item in entries if (item.get("external_metadata") or {}).get("source_id") == str(source_id)]
    return {"items": entries} if isinstance(entries, list) else result


def forget(db: Session, actor: User, project_id: uuid.UUID, data_id: str, client: CogneeClient | None = None) -> Any:
    require_project_role(db, actor.id, project_id, "editor")
    dataset = _dataset(db, project_id, client or CogneeClient(), create=False)
    result = (client or CogneeClient()).forget(dataset_id=dataset.cognee_dataset_id, data_id=data_id)
    _activity(db, project_id, actor, "memory_forget", "删除记忆条目")
    db.commit()
    return result


def list_sessions(db: Session, actor: User, project_id: uuid.UUID, client: CogneeClient | None = None) -> Any:
    require_project_role(db, actor.id, project_id, "editor")
    client = client or CogneeClient()
    dataset = _dataset(db, project_id, client, create=False)
    sessions = client.list_sessions(dataset.cognee_dataset_id) or []
    return [summary for item in sessions if (summary := _session_summary(db, project_id, item, client)) is not None]


def get_session_detail(
    db: Session, actor: User, project_id: uuid.UUID, session_id: str, client: CogneeClient | None = None
) -> dict:
    client = client or CogneeClient()
    summaries = list_sessions(db, actor, project_id, client)
    summary = next((item for item in summaries if item["session_id"] == session_id), None)
    if summary is None:
        raise not_found("会话不属于当前项目")
    detail = client.get_session(session_id)
    return {
        "session_id": session_id,
        "business_session_id": summary["business_session_id"],
        "source_id": summary["source_id"],
        "source_name": summary.get("source_name"),
        "source_kind": summary.get("source_kind"),
        "status": detail.get("effective_status") or detail.get("status"),
        "qas": detail.get("qas", []),
        "traces": detail.get("traces", []),
    }


def clear(db: Session, actor: User, project_id: uuid.UUID, confirmed: bool, client: CogneeClient | None = None) -> None:
    require_project_role(db, actor.id, project_id, "editor")
    if actor.is_agent:
        raise permission_denied("仅人类可清空项目记忆")
    if not confirmed:
        raise invalid_request("必须确认清空全部项目记忆")
    client = client or CogneeClient()
    dataset = _dataset(db, project_id, client)
    prefix = f"zeichen:{project_id}:"
    for item in client.list_sessions(dataset.cognee_dataset_id) or []:
        session_id = (item.get("id") or item.get("session_id")) if isinstance(item, dict) else item
        if session_id and str(session_id).startswith(prefix):
            client.delete_session(str(session_id))
    client.delete_dataset(dataset.cognee_dataset_id)
    db.delete(dataset)
    _activity(db, project_id, actor, "memory_clear", "清空全部项目记忆")
    db.commit()


def purge_project(db: Session, project_id: uuid.UUID, client: CogneeClient | None = None) -> None:
    """Permanently remove both the dataset and explicitly enumerated sessions."""
    row = db.scalar(select(MemoryDataset).where(MemoryDataset.project_id == project_id))
    if row is None:
        return
    client = client or CogneeClient()
    prefix = f"zeichen:{project_id}:"
    for item in client.list_sessions(row.cognee_dataset_id) or []:
        session_id = (item.get("id") or item.get("session_id")) if isinstance(item, dict) else item
        if session_id and str(session_id).startswith(prefix):
            client.delete_session(str(session_id))
    client.delete_dataset(row.cognee_dataset_id)
    db.delete(row)
