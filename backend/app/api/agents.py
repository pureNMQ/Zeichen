"""附属 Agent 自助 API(ADR 0004):/api/my-agent 全集。

旧 admin 代建端点(/api/agents 全集)已移除;admin 保留紧急吊销,挂 members 路由。
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import AgentProfileUpdate, KeyIssue, KeyReveal, MyAgentCreate
from ..services import agents as agents_service
from .deps import current_user

router = APIRouter(prefix="/api/my-agent", tags=["agents"])


@router.get("")
def get_my_agent(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    agent = agents_service.get_owned_agent(db, user.id)
    if agent is None:
        return {"agent": None}
    return {"agent": agents_service.agent_detail(db, agent)}


@router.post("", status_code=201)
def create_my_agent(
    body: MyAgentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    agent = agents_service.create_agent(db, user, body.username.strip())
    return {"agent": agents_service.agent_detail(db, agent)}


@router.patch("")
def update_my_agent(
    body: AgentProfileUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    agent = agents_service.require_owned_agent(db, user.id)
    from ..services.user_profiles import payload, update_profile

    update_profile(db, user, agent.id, body.nickname)
    return {"agent": agents_service.agent_detail(db, agent)}


@router.delete("")
def delete_my_agent(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    agents_service.delete_agent(db, user)
    return {"ok": True}


@router.post("/keys", status_code=201)
def issue_key(
    body: KeyIssue, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    key, token = agents_service.issue_key(db, user, body.note)
    return {"id": str(key.id), "token": token, "note": key.note}


@router.post("/keys/{key_id}/reveal")
def reveal_key(
    key_id: uuid.UUID,
    body: KeyReveal,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    token = agents_service.reveal_key(db, user, body.password, key_id)
    return {"token": token}


@router.delete("/keys/{key_id}")
def revoke_key(
    key_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    agents_service.revoke_key(db, user, key_id)
    return {"ok": True}
