"""API 依赖:当前用户(会话 cookie)、当前管理员、设密码短令牌。"""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security import PENDING_PASSWORD, SESSION, TokenError, decode_token
from ..services.permissions import require_workspace_admin


def _user_from_payload(db: Session, payload: dict) -> User:
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = decode_token(token)
    except TokenError:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    if payload.get("typ") != SESSION:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    return _user_from_payload(db, payload)


def pending_password_user(request: Request, db: Session = Depends(get_db)) -> User:
    """设密码短令牌(typ=set_password)对应的用户;仅限 /auth/set-password 使用。"""
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    try:
        payload = decode_token(token)
    except TokenError:
        raise HTTPException(status_code=401, detail="会话无效或已过期")
    if payload.get("typ") != PENDING_PASSWORD:
        raise HTTPException(status_code=403, detail="当前会话不支持设置密码")
    return _user_from_payload(db, payload)


def current_admin(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    require_workspace_admin(db, user.id)
    return user
