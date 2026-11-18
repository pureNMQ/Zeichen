"""工作区成员(人类)管理:添加(首登设密码)/改角色/移除。仅 admin。

规格书 §5.1:admin 管成员;§5.3:成员直接添加(账号+角色),首登设密码。
移除 = 软删 user + 清 workspace/project 成员行;最后一名 admin 不可降级/移除。
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import ApiKey, PasswordSetupToken, ProjectMember, User, WorkspaceMember
from ..security import generate_password_setup_token, token_digest
from . import agents
from .permissions import effective_user_id, get_team, get_workspace_member, require_workspace_admin
from .user_profiles import display_name, payload as profile_payload

WORKSPACE_ROLES = ("admin", "member")
PASSWORD_SETUP_LINK_TTL = timedelta(hours=24)


def list_members(db: Session) -> list[tuple[User, str]]:
    team = get_team(db)
    rows = db.execute(
        select(User, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.team_id == team.id,
            User.deleted_at.is_(None),
            User.is_agent.is_(False),
        )
        .order_by(User.created_at)
    ).all()
    return [(u, role) for u, role in rows]


def member_summary(user: User) -> dict:
    return {
        **profile_payload(user), "created_at": user.created_at.isoformat(),
        "is_bootstrap": user.is_bootstrap, "has_password": bool(user.password_hash),
    }


def workspace_roster(db: Session, actor: User) -> list[dict]:
    if get_workspace_member(db, actor.id) is None:
        raise permission_denied("仅工作区成员可查看名册")
    principal_id = effective_user_id(db, actor.id)
    owned = agents.owned_agents_map(db)
    items = []
    for user, role in list_members(db):
        agent = owned.get(user.id)
        agent_info = None
        if agent is not None:
            agent_info = {
                "id": str(agent.id), "username": agent.username, "nickname": agent.nickname,
                "display_name": display_name(agent), "created_at": agent.created_at.isoformat(),
                "active_keys": agents.agent_detail(db, agent)["active_keys"],
            }
        items.append({**member_summary(user), "role": role, "is_self": user.id == principal_id, "agent": agent_info})
    return items


def inactive_roster(db: Session, actor: User) -> list[dict]:
    require_workspace_admin(db, actor.id)
    return [{**member_summary(user), "deactivated_at": user.deleted_at.isoformat()} for user in list_inactive_members(db)]


def _get_active_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise not_found("成员不存在")
    return user


def _issue_password_setup_token(db: Session, user: User, ttl: timedelta = PASSWORD_SETUP_LINK_TTL) -> str:
    """Store only the digest. A zero TTL reserves setup for a human administrator."""
    raw_token = generate_password_setup_token()
    expires_at = datetime.now(timezone.utc) + ttl
    setup = db.scalar(select(PasswordSetupToken).where(PasswordSetupToken.user_id == user.id))
    if setup is None:
        db.add(
            PasswordSetupToken(
                user_id=user.id, token_hash=token_digest(raw_token), expires_at=expires_at
            )
        )
    else:
        setup.token_hash = token_digest(raw_token)
        setup.expires_at = expires_at
        setup.used_at = None
    return raw_token


def _prepare_password_setup(db: Session, user: User, actor: User) -> str | None:
    if actor.is_agent:
        # Even before a human issues a link, this account must require link-based
        # setup. No setup row would identify it as a legacy first-login account.
        _issue_password_setup_token(db, user, ttl=timedelta(0))
        return None
    return _issue_password_setup_token(db, user)


def create_member(db: Session, actor: User, username: str, role: str) -> tuple[User, str | None]:
    require_workspace_admin(db, actor.id)
    username = username.strip()
    if not username or len(username) > 64:
        raise invalid_request("用户名须为 1 至 64 个字符")
    if role not in WORKSPACE_ROLES:
        raise invalid_request("角色不合法")
    exists = db.scalar(select(User).where(User.username == username))
    if exists is not None:
        raise conflict("账号已存在")
    user = User(username=username, password_hash="", is_agent=False)
    team = get_team(db)
    db.add(user)
    db.flush()
    db.add(
        WorkspaceMember(team_id=team.id, user_id=user.id, role=role, created_by=actor.id)
    )
    raw_token = _prepare_password_setup(db, user, actor)
    db.commit()
    return user, raw_token


def regenerate_password_setup_link(db: Session, user_id: uuid.UUID) -> str:
    user = _get_active_user(db, user_id)
    if user.is_agent:
        raise invalid_request("Agent accounts do not support password login")
    if user.password_hash:
        raise conflict("成员已完成设密，不能重新生成设密链接")
    raw_token = _issue_password_setup_token(db, user)
    db.commit()
    return raw_token


def update_role(db: Session, actor: User, user_id: uuid.UUID, role: str) -> User:
    require_workspace_admin(db, actor.id)
    if role not in WORKSPACE_ROLES:
        raise invalid_request("角色不合法")
    user = _get_active_user(db, user_id)
    if user.is_agent:
        raise invalid_request("agent 不在此页管理")
    wm = get_team(db)
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.team_id == wm.id, WorkspaceMember.user_id == user_id
        )
    )
    if membership is None:
        raise not_found("成员不存在")
    if user.id == effective_user_id(db, actor.id):
        raise conflict("不能修改自己的角色")
    if user.is_bootstrap:
        raise conflict("首用户的角色已锁定")
    membership.role = role
    db.commit()
    return user


def remove_member(db: Session, actor: User, user_id: uuid.UUID) -> None:
    require_workspace_admin(db, actor.id)
    user = db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update())
    if user is None:
        raise not_found("成员不存在")
    team = get_team(db)
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.team_id == team.id, WorkspaceMember.user_id == user_id
        )
    )
    if membership is None:
        raise not_found("成员不存在")
    if user.id == effective_user_id(db, actor.id):
        raise conflict("不能移除自己")
    if user.is_bootstrap:
        raise conflict("首用户不能被移除")
    db.delete(membership)
    db.query(ProjectMember).filter(ProjectMember.user_id == user_id).delete()
    db.query(PasswordSetupToken).filter(PasswordSetupToken.user_id == user_id).delete()
    user.deleted_at = datetime.now(timezone.utc)
    user.session_epoch += 1
    # ADR 0004:主人被移除时,其附属 Agent 随之停用并吊销全部 key(同事务)
    now = user.deleted_at
    owned_agents = db.scalars(
        select(User).where(User.owner_id == user_id, User.deleted_at.is_(None))
    ).all()
    for agent in owned_agents:
        agent.deleted_at = now
        db.query(ApiKey).filter(ApiKey.user_id == agent.id, ApiKey.revoked_at.is_(None)).update(
            {ApiKey.revoked_at: now}
        )
    db.commit()


def list_inactive_members(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(
        User.is_agent.is_(False), User.deleted_at.is_not(None),
    ).order_by(User.deleted_at.desc(), User.id)))


def reactivate_member(db: Session, actor: User, user_id: uuid.UUID) -> tuple[User, str | None]:
    require_workspace_admin(db, actor.id)
    user = db.scalar(select(User).where(User.id == user_id, User.is_agent.is_(False)).with_for_update())
    if user is None or user.deleted_at is None:
        raise not_found("已停用的成员不存在")
    team = get_team(db)
    # There may be incomplete legacy membership cleanup. Never grant back old permissions.
    db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).delete()
    db.query(ProjectMember).filter(ProjectMember.user_id == user.id).delete()
    db.add(WorkspaceMember(team_id=team.id, user_id=user.id, role="member", created_by=actor.id))
    user.deleted_at = None
    user.session_epoch += 1
    setup = None if user.password_hash else _prepare_password_setup(db, user, actor)
    db.commit()
    return user, setup
