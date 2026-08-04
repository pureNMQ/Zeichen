"""认证 API:首用户引导 / 登录 / 设密码 / 改密码 / 退出 / me。"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import ChangePassword, SetPassword, SetPasswordWithToken, UsernamePassword
from ..security import PENDING_PASSWORD, SESSION, create_token
from ..services import auth as auth_service
from ..services.permissions import get_workspace_member
from .deps import current_user, pending_password_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

SET_PASSWORD_TTL = 3600  # 设密码短令牌 1 小时


def _user_payload(user: User, db: Session) -> dict:
    wm = get_workspace_member(db, user.id)
    return {
        "id": str(user.id),
        "username": user.username,
        "is_agent": user.is_agent,
        "workspace_role": wm.role if wm else None,
    }


def _set_cookie(response: Response, user_id: str, typ: str, ttl: int | None = None) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_token(user_id, typ, ttl),
        max_age=ttl or settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(get_settings().session_cookie_name, path="/")


@router.get("/bootstrap")
def bootstrap_status(db: Session = Depends(get_db)) -> dict:
    count = db.scalar(select(func.count()).select_from(User))
    return {"needs_bootstrap": count == 0}


@router.post("/bootstrap")
def bootstrap(body: UsernamePassword, response: Response, db: Session = Depends(get_db)) -> dict:
    user = auth_service.bootstrap(db, body.username.strip(), body.password)
    _set_cookie(response, str(user.id), SESSION)
    return {"needs_password": False, "user": _user_payload(user, db)}


@router.post("/login")
def login(body: UsernamePassword, response: Response, db: Session = Depends(get_db)) -> dict:
    user, needs_password = auth_service.login(db, body.username.strip(), body.password)
    if needs_password:
        _set_cookie(response, str(user.id), PENDING_PASSWORD, SET_PASSWORD_TTL)
        return {"needs_password": True}
    _set_cookie(response, str(user.id), SESSION)
    return {"needs_password": False, "user": _user_payload(user, db)}


@router.post("/set-password")
def set_password(
    body: SetPassword,
    response: Response,
    user: User = Depends(pending_password_user),
    db: Session = Depends(get_db),
) -> dict:
    auth_service.set_password(db, user.id, body.password)
    _set_cookie(response, str(user.id), SESSION)
    return {"needs_password": False, "user": _user_payload(user, db)}


@router.post("/set-password-with-token")
def set_password_with_token(
    body: SetPasswordWithToken, response: Response, db: Session = Depends(get_db)
) -> dict:
    user = auth_service.set_password_with_token(db, body.token, body.password)
    _set_cookie(response, str(user.id), SESSION)
    return {"needs_password": False, "user": _user_payload(user, db)}


@router.get("/password-setup")
def password_setup_info(
    token: str = Query(min_length=32, max_length=256), db: Session = Depends(get_db)
) -> dict:
    user = auth_service.get_password_setup_user(db, token)
    return {"username": user.username}


@router.post("/change-password")
def change_password(
    body: ChangePassword,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    auth_service.change_password(db, user, body.old_password, body.new_password)
    return {"ok": True}


@router.post("/logout")
def logout(response: Response) -> dict:
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return _user_payload(user, db)
