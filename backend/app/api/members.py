"""工作区成员 API:全员可读;添加、改角色和移除仅 admin。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..config import get_settings
from ..models import User
from ..schemas import MemberCreate, MemberUpdate
from ..services import agents as agents_service
from ..services import members as members_service
from ..services.members import member_summary
from .deps import current_admin, current_user

router = APIRouter(prefix="/api/members", tags=["members"])


def _password_setup_url(token: str) -> str:
    return get_settings().web_base_url.rstrip("/") + f"/set-password?token={token}"


@router.get("")
def list_members(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return members_service.workspace_roster(db, user)


@router.post("", status_code=201)
def create_member(
    body: MemberCreate,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    user, token = members_service.create_member(db, admin, body.username.strip(), body.role)
    return {
        **member_summary(user),
        "role": body.role,
        "password_setup_url": _password_setup_url(token),
    }


@router.post("/{user_id}/password-setup-link")
def regenerate_password_setup_link(
    user_id: uuid.UUID,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    token = members_service.regenerate_password_setup_link(db, user_id)
    return {"password_setup_url": _password_setup_url(token)}


@router.get("/inactive")
def list_inactive_members(
    admin: User = Depends(current_admin), db: Session = Depends(get_db),
) -> list[dict]:
    return members_service.inactive_roster(db, admin)


@router.post("/inactive/{user_id}/reactivate")
def reactivate_member(
    user_id: uuid.UUID, admin: User = Depends(current_admin), db: Session = Depends(get_db),
) -> dict:
    user, token = members_service.reactivate_member(db, admin, user_id)
    return {**member_summary(user), "role": "member", "password_setup_url": _password_setup_url(token) if token else None}


@router.patch("/{user_id}")
def update_member(
    user_id: uuid.UUID,
    body: MemberUpdate,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    user = members_service.update_role(db, admin, user_id, body.role)
    return {**member_summary(user), "role": body.role}


@router.delete("/{user_id}")
def remove_member(
    user_id: uuid.UUID, admin: User = Depends(current_admin), db: Session = Depends(get_db)
) -> dict:
    members_service.remove_member(db, admin, user_id)
    return {"ok": True}


@router.post("/{member_id}/agent/revoke-keys")
def revoke_member_agent_keys(
    member_id: uuid.UUID,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    """紧急吊销:仅失效成员附属 Agent 的全部 key,不接触明文、不可签发(ADR 0004)。"""
    agent = agents_service.get_owned_agent(db, member_id)
    if agent is None:
        from ..errors import not_found

        raise not_found("该成员没有附属 Agent")
    revoked = agents_service.admin_revoke_keys(db, agent.id)
    return {"revoked": revoked}
