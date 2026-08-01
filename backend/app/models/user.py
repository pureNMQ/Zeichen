"""user / api_key 及工作区角色常量。

规格书 §2.2:人类与 agent 同表,is_agent 区分;username 为登录账号。
api_key:仅 agent 签发,多 key 并存、独立吊销(revoked_at 即生命周期终点,不再叠加软删)。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin

WORKSPACE_ROLE_VALUES = ("admin", "member")


class User(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "user"
    __table_args__ = (CheckConstraint("username <> ''", name="ck_user_username_not_empty"),)

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class ApiKey(IdMixin, TimestampMixin, Base):
    __tablename__ = "api_key"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # 明文仅加密存(服务端密钥 AES-GCM),回看时经管理员密码验证后解密展示
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="api_keys")
