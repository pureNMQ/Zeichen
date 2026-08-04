"""认证域服务:首用户引导、登录、设密码、改密码。

规格书 §5.3:首用户引导注册为 admin;成员直接添加(账号+角色),首登设密码(无 SMTP)。
agent 不走密码登录(API key),登录接口对 is_agent 直接拒绝。
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied, unauthorized
from ..models import PasswordSetupToken, Team, User, WorkspaceMember
from ..security import hash_password, token_digest, verify_password


def bootstrap(db: Session, username: str, password: str) -> User:
    """首用户引导:创建单例 Team + 首个 admin。已有任何用户则 409。"""
    if db.scalar(select(func.count()).select_from(User)) > 0:
        raise conflict("工作区已初始化,请直接登录")
    user = User(
        username=username,
        password_hash=hash_password(password),
        is_agent=False,
        is_bootstrap=True,
    )
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
        # Accounts created with a setup link cannot be activated by merely
        # supplying an arbitrary password. Blank legacy accounts still use
        # the pre-existing pending-password flow.
        setup_exists = db.scalar(
            select(PasswordSetupToken.id).where(PasswordSetupToken.user_id == user.id)
        )
        if setup_exists is not None:
            raise unauthorized("Use the password-setup link provided by your administrator")
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


def get_password_setup_user(db: Session, token: str) -> User:
    """Return the member named by a currently usable setup credential."""
    now = datetime.now(timezone.utc)
    setup = db.scalar(
        select(PasswordSetupToken).where(
            PasswordSetupToken.token_hash == token_digest(token),
            PasswordSetupToken.used_at.is_(None),
            PasswordSetupToken.expires_at > now,
        )
    )
    if setup is None:
        raise unauthorized("Password setup link is invalid, used, or expired")
    user = db.get(User, setup.user_id)
    if user is None or user.deleted_at is not None or user.is_agent:
        raise unauthorized("Password setup link is invalid, used, or expired")
    return user


def set_password_with_token(db: Session, token: str, password: str) -> User:
    """Consume a valid setup credential and establish a password atomically."""
    now = datetime.now(timezone.utc)
    setup = db.scalar(
        select(PasswordSetupToken).where(
            PasswordSetupToken.token_hash == token_digest(token),
            PasswordSetupToken.used_at.is_(None),
            PasswordSetupToken.expires_at > now,
        )
    )
    if setup is None:
        raise unauthorized("Password setup link is invalid, used, or expired")
    user = db.get(User, setup.user_id)
    if user is None or user.deleted_at is not None or user.is_agent:
        raise unauthorized("Password setup link is invalid, used, or expired")

    # A conditional update ensures simultaneous requests cannot consume the
    # same link twice. Password update and consumption share one transaction.
    consumed = db.execute(
        update(PasswordSetupToken)
        .where(
            PasswordSetupToken.id == setup.id,
            PasswordSetupToken.used_at.is_(None),
            PasswordSetupToken.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise unauthorized("Password setup link is invalid, used, or expired")
    user.password_hash = hash_password(password)
    db.commit()
    return user


def change_password(db: Session, user: User, old_password: str, new_password: str) -> None:
    if not user.password_hash or not verify_password(old_password, user.password_hash):
        raise permission_denied("原密码不正确")
    user.password_hash = hash_password(new_password)
    db.commit()
