"""认证域服务:首用户引导、登录、设密码、改密码。

规格书 §5.3:首用户引导注册为 admin;成员直接添加(账号+角色),首登设密码(无 SMTP)。
agent 不走密码登录(API key),登录接口对 is_agent 直接拒绝。
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied, unauthorized
from ..models import Team, User, WorkspaceMember
from ..security import hash_password, verify_password


def bootstrap(db: Session, username: str, password: str) -> User:
    """首用户引导:创建单例 Team + 首个 admin。已有任何用户则 409。"""
    if db.scalar(select(func.count()).select_from(User)) > 0:
        raise conflict("工作区已初始化,请直接登录")
    user = User(username=username, password_hash=hash_password(password), is_agent=False)
    team = Team(name="贼船")
    db.add_all([user, team])
    db.flush()
    db.add(WorkspaceMember(team_id=team.id, user_id=user.id, role="admin", created_by=user.id))
    db.commit()
    return user


def login(db: Session, username: str, password: str) -> tuple[User, bool]:
    """返回 (user, needs_password)。凭证错误抛 401;agent 抛 403。"""
    user = db.scalar(
        select(User).where(User.username == username, User.deleted_at.is_(None))
    )
    if user is None:
        raise unauthorized("用户名或密码错误")
    if user.is_agent:
        raise permission_denied("Agent 账号通过 API key 访问")
    if not user.password_hash:
        return user, True
    if not verify_password(password, user.password_hash):
        raise unauthorized("用户名或密码错误")
    return user, False


def set_password(db: Session, user_id: uuid.UUID, password: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise unauthorized("会话无效或已过期")
    user.password_hash = hash_password(password)
    db.commit()
    return user


def change_password(db: Session, user: User, old_password: str, new_password: str) -> None:
    if not user.password_hash or not verify_password(old_password, user.password_hash):
        raise permission_denied("原密码不正确")
    user.password_hash = hash_password(new_password)
    db.commit()
