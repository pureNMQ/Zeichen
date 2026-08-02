"""工作区成员(人类)管理:添加(首登设密码)/改角色/移除。仅 admin。

规格书 §5.1:admin 管成员;§5.3:成员直接添加(账号+角色),首登设密码。
移除 = 软删 user + 清 workspace/project 成员行;最后一名 admin 不可降级/移除。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import ProjectMember, User, WorkspaceMember
from .permissions import get_team

WORKSPACE_ROLES = ("admin", "member")


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


def admin_count(db: Session) -> int:
    team = get_team(db)
    return db.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(
            WorkspaceMember.team_id == team.id,
            WorkspaceMember.role == "admin",
            User.deleted_at.is_(None),
            User.is_agent.is_(False),
        )
    )


def _get_active_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise not_found("成员不存在")
    return user


def create_member(db: Session, actor: User, username: str, role: str) -> User:
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
    db.commit()
    return user


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
    if membership.role == "admin" and role != "admin" and admin_count(db) <= 1:
        raise conflict("不能降级最后一名管理员")
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
    if membership.role == "admin" and admin_count(db) <= 1:
        raise conflict("不能移除最后一名管理员")
    db.delete(membership)
    db.query(ProjectMember).filter(ProjectMember.user_id == user_id).delete()
    user.deleted_at = datetime.now(timezone.utc)
    db.commit()
