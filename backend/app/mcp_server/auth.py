"""TokenVerifier:把 Bearer API key 解析为 agent 主体(接入 02 的 api_key 服务)。

mcp SDK 1.29:FastMCP(auth=AuthSettings, token_verifier=…) 挂
AuthenticationMiddleware(BearerAuthBackend) + AuthContextMiddleware,
验证结果存 contextvar `auth_context_var`(mcp.server.auth.middleware.auth_context)。
"""

import uuid

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.provider import AccessToken, TokenVerifier
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..errors import unauthorized
from ..models import ApiKey, User
from ..security import token_digest


class ApiKeyTokenVerifier(TokenVerifier):
    """按 token_hash 查未吊销 key,主体必须是未删除的 agent(规格书 §5.3)。"""

    async def verify_token(self, token: str) -> AccessToken | None:
        digest = token_digest(token)
        with SessionLocal() as db:
            key = db.scalar(
                select(ApiKey).where(
                    ApiKey.token_hash == digest, ApiKey.revoked_at.is_(None)
                )
            )
            if key is None:
                return None
            user = db.get(User, key.user_id)
            if user is None or user.deleted_at is not None or not user.is_agent:
                return None
            return AccessToken(
                token=token,
                client_id=str(key.id),
                scopes=[],
                subject=str(user.id),
                claims={"key_id": str(key.id)},
            )


def current_principal(db: Session) -> User:
    """当前请求的 agent 主体;缺凭据/主体失效 → unauthorized。"""
    auth_user = auth_context_var.get()
    if auth_user is None or auth_user.access_token.subject is None:
        raise unauthorized("缺少有效 API key")
    user = db.get(User, uuid.UUID(auth_user.access_token.subject))
    if user is None or user.deleted_at is not None:
        raise unauthorized("主体不存在")
    return user
