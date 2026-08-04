"""密码哈希、会话 JWT、API key 加解密。

- 密码:argon2(pwdlib)
- 会话:HS256 JWT,payload.typ = session / set_password(仅限设密码的短命令牌)
- API key:明文只在签发瞬间返回,落库 sha256(token_hash,查重/鉴权)+ AES-GCM 密文
  (token_encrypted,服务端密钥派生;回看时经管理员密码验证后解密)
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
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


def _crypto_key() -> bytes:
    return hashlib.sha256(get_settings().session_secret.encode()).digest()


def encrypt_secret(plaintext: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_crypto_key()).encrypt(nonce, plaintext.encode(), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode()


def decrypt_secret(blob: str) -> str:
    raw = base64.urlsafe_b64decode(blob.encode())
    return AESGCM(_crypto_key()).decrypt(raw[:12], raw[12:], None).decode()


def generate_api_token() -> str:
    return "zc_" + secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_password_setup_token() -> str:
    """Generate an opaque credential for a one-time password-setup link."""
    return secrets.token_urlsafe(32)
