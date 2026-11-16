"""密码哈希、会话 JWT、API key 生成与校验。

- 密码:argon2(pwdlib)
- 会话:HS256 JWT,payload.typ = session / set_password(仅限设密码的短命令牌)
- API key:明文仅签发时返回，服务端保留 SHA-256 校验值。
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from .config import get_settings

_password = PasswordHash.recommended()

SESSION = "session"
PENDING_PASSWORD = "set_password"


class TokenError(Exception):
    """会话令牌无效或过期。"""


def hash_password(password: str) -> str:
    return _password.hash(password)


def verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        return _password.verify(password, stored)
    except Exception:
        return False


def create_token(user_id: str, typ: str, ttl_seconds: int | None = None) -> str:
    settings = get_settings()
    ttl = ttl_seconds or settings.session_ttl_seconds
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "typ": typ,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().session_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenError("会话无效或已过期") from exc


def generate_api_token() -> str:
    return "zc_" + secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_password_setup_token() -> str:
    """Generate an opaque credential for a one-time password-setup link."""
    return secrets.token_urlsafe(32)
