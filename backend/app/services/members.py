"""工作区成员(人类)管理:添加(首登设密码)/改角色/移除。仅 admin。

规格书 §5.1:admin 管成员;§5.3:成员直接添加(账号+角色),首登设密码。
移除 = 软删 user + 清 workspace/project 成员行;最后一名 admin 不可降级/移除。
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import PasswordSetupToken, ProjectMember, User, WorkspaceMember
from ..security import generate_password_setup_token, token_digest
from .permissions import get_team

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


def _get_active_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise not_found("成员不存在")
    return user


def _issue_password_setup_token(db: Session, user: User) -> str:
    """Create or replace a 24-hour setup credential; only its digest is stored."""
    raw_token = generate_password_setup_token()
    expires_at = datetime.now(timezone.utc) + PASSWORD_SETUP_LINK_TTL
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


def create_member(db: Session, actor: User, username: str, role: str) -> tuple[User, str]:
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
    raw_token = _issue_password_setup_token(db, user)
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
    if user.id == actor.id:
        raise conflict("不能修改自己的角色")
    if user.is_bootstrap:
        raise conflict("首用户的角色已锁定")
    membership.role = role
    db.commit()
    return user


def remove_member(db: Session, actor: User, user_id: uuid.UUID) -> None:
    user = _get_active_user(db, user_id)
    team = get_team(db)
    membership = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.team_id == team.id, WorkspaceMember.user_id == user_id
        )
    )
    if membership is None:
        raise not_found("成员不存在")
    if user.id == actor.id:
        raise conflict("不能移除自己")
    if user.is_bootstrap:
        raise conflict("首用户不能被移除")
    db.delete(membership)
    db.query(ProjectMember).filter(ProjectMember.user_id == user_id).delete()
    db.query(PasswordSetupToken).filter(PasswordSetupToken.user_id == user_id).delete()
    user.deleted_at = datetime.now(timezone.utc)
    db.commit()
