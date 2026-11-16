"""附属 Agent 生命周期(ADR 0004):成员自有、权限随主人、key 仅主人可取。

- 每个工作区成员至多一个附属 Agent,由成员本人创建(username 全局唯一,创建后不可改);
- Agent 无独立授权行,判权经 permissions.effective_user_id 动态继承主人;
- key 仅主人可签发/吊销，明文仅签发时返回；工作区 admin 仅保留紧急吊销；
- 主人被移除/软删时 Agent 随之停用并吊销全部 key(联动在 members.remove_member)。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import ApiKey, User
from ..security import generate_api_token, token_digest
from .user_profiles import payload as profile_payload


def get_owned_agent(db: Session, owner_id: uuid.UUID) -> User | None:
    """主人的附属 Agent(未停用);没有则 None。"""
    return db.scalar(
        select(User).where(
            User.owner_id == owner_id,
            User.is_agent.is_(True),
            User.deleted_at.is_(None),
        )
    )


def owned_agents_map(db: Session) -> dict[uuid.UUID, User]:
    """全部存活附属 Agent 按主人 id 索引(成员列表摘要用)。"""
    rows = db.scalars(
        select(User).where(
            User.is_agent.is_(True),
            User.deleted_at.is_(None),
            User.owner_id.is_not(None),
        )
    ).all()
    return {a.owner_id: a for a in rows}


def is_owner_of(db: Session, owner_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
    agent = db.get(User, agent_id)
    return (
        agent is not None
        and agent.is_agent
        and agent.owner_id == owner_id
        and agent.deleted_at is None
    )


def create_agent(db: Session, owner: User, username: str) -> User:
    if owner.is_agent:
        raise permission_denied("附属 Agent 不能再创建 Agent")
    if get_owned_agent(db, owner.id) is not None:
        raise conflict("已创建附属 Agent")
    username = username.strip()
    if not username:
        raise invalid_request("用户名不能为空")
    if len(username) > 64:
        raise invalid_request("用户名过长")
    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None:
        if existing.deleted_at is not None:
            raise conflict("该用户名已被已删除账号占用,请换一个用户名")
        raise conflict("账号已存在")
    agent = User(
        username=username,
        password_hash="",
        is_agent=True,
        owner_id=owner.id,
        created_by=owner.id,
    )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError:
        # 并发窗口内查重漏判,由唯一索引兜底;按库内既成事实回精确 409
        db.rollback()
        if get_owned_agent(db, owner.id) is not None:
            raise conflict("已创建附属 Agent")
        raise conflict("账号已存在")
    db.refresh(agent)
    return agent


def delete_agent(db: Session, owner: User) -> None:
    """主人自助删除:软删 Agent 并同事务吊销全部 key(历史署名保留)。

    用户名仍被软删行占用,重建须换用户名(create_agent 的 409 文案已区分)。
    """
    agent = require_owned_agent(db, owner.id)
    now = datetime.now(timezone.utc)
    agent.deleted_at = now
    db.query(ApiKey).filter(
        ApiKey.user_id == agent.id, ApiKey.revoked_at.is_(None)
    ).update({ApiKey.revoked_at: now})
    db.commit()


def require_owned_agent(db: Session, owner_id: uuid.UUID) -> User:
    agent = get_owned_agent(db, owner_id)
    if agent is None:
        raise not_found("尚未创建附属 Agent")
    return agent


def key_payload(key: ApiKey) -> dict:
    return {
        "id": str(key.id),
        "note": key.note,
        "created_at": key.created_at.isoformat(),
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


def agent_detail(db: Session, agent: User) -> dict:
    """管理弹窗数据源:keys 仅含活跃 key(REQ-53),吊销条目即时消失,与 active_keys 一致。"""
    keys = list(
        db.scalars(
            select(ApiKey).where(ApiKey.user_id == agent.id, ApiKey.revoked_at.is_(None))
            .order_by(ApiKey.created_at.desc())
        ).all()
    )
    return {
        **profile_payload(agent),
        "created_at": agent.created_at.isoformat(),
        "active_keys": len(keys),
        "keys": [key_payload(k) for k in keys],
    }


def issue_key(db: Session, owner: User, note: str | None) -> tuple[ApiKey, str]:
    agent = require_owned_agent(db, owner.id)
    token = generate_api_token()
    key = ApiKey(
        user_id=agent.id,
        token_hash=token_digest(token),
        note=note,
    )
    db.add(key)
    db.commit()
    return key, token


def revoke_key(db: Session, owner: User, key_id: uuid.UUID) -> None:
    agent = require_owned_agent(db, owner.id)
    key = db.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == agent.id))
    if key is None:
        raise not_found("API key 不存在")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        db.commit()


def admin_revoke_keys(db: Session, agent_id: uuid.UUID) -> int:
    """工作区 admin 紧急吊销:仅失效,不接触明文,不可签发。"""
    agent = db.get(User, agent_id)
    if agent is None or not agent.is_agent:
        raise not_found("Agent 不存在")
    now = datetime.now(timezone.utc)
    revoked = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == agent.id, ApiKey.revoked_at.is_(None))
        .update({ApiKey.revoked_at: now})
    )
    db.commit()
    return revoked
