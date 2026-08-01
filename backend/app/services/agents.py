"""Agent 与 API key 生命周期管理。仅 admin。

规格书 §5.3:key 仅 agent 签发、多 key 并存、独立吊销;明文哈希存储但可回看
(管理员输入自己密码验证);删除 agent = 软删 + 全吊销 + 清授权(项目成员/记忆互通)。
"""

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ApiKey, MemoryGrant, Project, ProjectMember, User
from ..security import (
    decrypt_secret,
    encrypt_secret,
    generate_api_token,
    token_digest,
    verify_password,
)
from .permissions import is_admin


def _get_agent(db: Session, agent_id: uuid.UUID) -> User:
    agent = db.get(User, agent_id)
    if agent is None or agent.deleted_at is not None or not agent.is_agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return agent


def create_agent(db: Session, actor: User, username: str, grants: list[dict]) -> User:
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="账号已存在")
    agent = User(
        username=username,
        password_hash="",
        is_agent=True,
        created_by=actor.id,
    )
    db.add(agent)
    db.flush()
    _apply_grants(db, agent, grants)
    db.commit()
    return agent


def list_agents(db: Session) -> list[User]:
    return list(
        db.scalars(
            select(User).where(User.is_agent.is_(True), User.deleted_at.is_(None)).order_by(
                User.created_at
            )
        ).all()
    )


def update_agent(
    db: Session,
    actor: User,
    agent_id: uuid.UUID,
    username: str | None = None,
    grants: list[dict] | None = None,
) -> User:
    agent = _get_agent(db, agent_id)
    if username is not None and username != agent.username:
        if db.scalar(select(User).where(User.username == username)) is not None:
            raise HTTPException(status_code=409, detail="账号已存在")
        agent.username = username
    if grants is not None:
        db.query(ProjectMember).filter(ProjectMember.user_id == agent.id).delete()
        _apply_grants(db, agent, grants)
    db.commit()
    return agent


def _apply_grants(db: Session, agent: User, grants: list[dict]) -> None:
    for g in grants:
        project = db.scalar(
            select(Project).where(Project.id == g["project_id"], Project.deleted_at.is_(None))
        )
        if project is None:
            raise HTTPException(status_code=400, detail="授权指向的项目不存在")
        db.add(
            ProjectMember(
                project_id=project.id, user_id=agent.id, role=g["role"], created_by=agent.created_by
            )
        )


def delete_agent(db: Session, actor: User, agent_id: uuid.UUID) -> None:
    agent = _get_agent(db, agent_id)
    now = datetime.now(timezone.utc)
    agent.deleted_at = now
    db.query(ApiKey).filter(ApiKey.user_id == agent.id, ApiKey.revoked_at.is_(None)).update(
        {ApiKey.revoked_at: now}
    )
    db.query(ProjectMember).filter(ProjectMember.user_id == agent.id).delete()
    db.query(MemoryGrant).filter(
        (MemoryGrant.grantor_id == agent.id)
        | (MemoryGrant.viewer_agent_id == agent.id)
        | (MemoryGrant.target_agent_id == agent.id)
    ).delete()
    db.commit()


def issue_key(db: Session, agent_id: uuid.UUID, note: str | None) -> tuple[ApiKey, str]:
    agent = _get_agent(db, agent_id)
    token = generate_api_token()
    key = ApiKey(
        user_id=agent.id,
        token_hash=token_digest(token),
        token_encrypted=encrypt_secret(token),
        note=note,
    )
    db.add(key)
    db.commit()
    return key, token


def list_keys(db: Session, agent_id: uuid.UUID) -> list[ApiKey]:
    _get_agent(db, agent_id)
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == agent_id)
            .order_by(ApiKey.created_at.desc())
        ).all()
    )


def _get_key(db: Session, agent_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
    key = db.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == agent_id)
    )
    if key is None:
        raise HTTPException(status_code=404, detail="API key 不存在")
    return key


def reveal_key(
    db: Session, actor: User, password: str, agent_id: uuid.UUID, key_id: uuid.UUID
) -> str:
    """管理员输入自己的密码验证后,解密回看明文。"""
    if not is_admin(db, actor.id):
        raise HTTPException(status_code=403, detail="仅工作区管理员可回看 key")
    if not actor.password_hash or not verify_password(password, actor.password_hash):
        raise HTTPException(status_code=403, detail="密码验证失败")
    key = _get_key(db, agent_id, key_id)
    if key.revoked_at is not None:
        raise HTTPException(status_code=409, detail="key 已吊销,无法回看")
    return decrypt_secret(key.token_encrypted)


def revoke_key(db: Session, agent_id: uuid.UUID, key_id: uuid.UUID) -> None:
    _get_agent(db, agent_id)
    key = _get_key(db, agent_id, key_id)
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()
