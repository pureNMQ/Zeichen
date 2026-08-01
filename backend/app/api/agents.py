"""Agent API(仅 admin):创建 / 列表 / 更新授权 / 删除 + key 生命周期。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiKey, Project, ProjectMember, User
from ..schemas import AgentCreate, AgentUpdate, KeyIssue, KeyReveal
from ..services import agents as agents_service
from .deps import current_admin

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _grant_payload(db: Session, agent_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(Project.id, Project.name, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == agent_id, Project.deleted_at.is_(None))
        .order_by(Project.name)
    ).all()
    return [{"project_id": str(pid), "name": name, "role": role} for pid, name, role in rows]


def _agent_payload(db: Session, agent: User) -> dict:
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == agent.id)).all()
    active = sum(1 for k in keys if k.revoked_at is None)
    return {
        "id": str(agent.id),
        "username": agent.username,
        "created_at": agent.created_at.isoformat(),
        "grants": _grant_payload(db, agent.id),
        "key_count": len(keys),
        "active_keys": active,
    }


@router.get("")
def list_agents(admin: User = Depends(current_admin), db: Session = Depends(get_db)) -> list[dict]:
    return [_agent_payload(db, a) for a in agents_service.list_agents(db)]


@router.post("", status_code=201)
def create_agent(
    body: AgentCreate, admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> dict:
    agent = agents_service.create_agent(
        db, admin, body.username.strip(), [g.model_dump() for g in body.project_grants]
    )
    return _agent_payload(db, agent)


@router.patch("/{agent_id}")
def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    grants = [g.model_dump() for g in body.project_grants] if body.project_grants is not None else None
    agent = agents_service.update_agent(db, admin, agent_id, body.username, grants)
    return _agent_payload(db, agent)


@router.delete("/{agent_id}")
def delete_agent(
    agent_id: uuid.UUID, admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> dict:
    agents_service.delete_agent(db, admin, agent_id)
    return {"ok": True}


@router.get("/{agent_id}/keys")
def list_keys(
    agent_id: uuid.UUID, admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        {
            "id": str(k.id),
            "note": k.note,
            "created_at": k.created_at.isoformat(),
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        }
        for k in agents_service.list_keys(db, agent_id)
    ]


@router.post("/{agent_id}/keys", status_code=201)
def issue_key(
    agent_id: uuid.UUID,
    body: KeyIssue,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    key, token = agents_service.issue_key(db, agent_id, body.note)
    return {"id": str(key.id), "token": token, "note": key.note}


@router.post("/{agent_id}/keys/{key_id}/reveal")
def reveal_key(
    agent_id: uuid.UUID,
    key_id: uuid.UUID,
    body: KeyReveal,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    token = agents_service.reveal_key(db, admin, body.password, agent_id, key_id)
    return {"token": token}


@router.post("/{agent_id}/keys/{key_id}/revoke")
def revoke_key(
    agent_id: uuid.UUID,
    key_id: uuid.UUID,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    agents_service.revoke_key(db, agent_id, key_id)
    return {"ok": True}
