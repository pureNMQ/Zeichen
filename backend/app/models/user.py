"""user / api_key 及工作区角色常量。

规格书 §2.2:人类与 agent 同表,is_agent 区分;username 为登录账号。
ADR 0004(附属化):is_agent 行须带 owner_id 指向主人,权限完全继承;每主人至多一个。
api_key:仅 agent 签发,多 key 并存、独立吊销(revoked_at 即生命周期终点,不再叠加软删)。
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, CreatedByMixin, IdMixin, SoftDeleteMixin, TimestampMixin

WORKSPACE_ROLE_VALUES = ("admin", "member")


class User(IdMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base):
    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint("username <> ''", name="ck_user_username_not_empty"),
        CheckConstraint("owner_id IS NULL OR is_agent", name="ck_user_owner_only_for_agent"),
        # 软删即释放唯一占位:与 get_owned_agent 的存活判定保持同一谓词
        Index(
            "uq_user_owner_one_agent",
            "owner_id",
            unique=True,
            postgresql_where=text("owner_id IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("owner_id IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Current avatar attachment id. The Attachment row remains the storage and
    # lifecycle source of truth; keeping the id here makes replacement atomic.
    avatar: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # ADR 0004:附属 Agent 的主人;人类成员恒为 NULL。判权时动态解析主人角色。
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # The founding human account is permanently protected from workspace role
    # changes and removal.  It is deliberately a user-level property so the
    # protection survives membership lookups.
    is_bootstrap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")
    password_setup_token: Mapped["PasswordSetupToken | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class PasswordSetupToken(IdMixin, TimestampMixin, Base):
    """A single, short-lived password-setup credential for a human user.

    The raw credential is never persisted. Replacing the digest invalidates
    every older link for that user.
    """

    __tablename__ = "password_setup_token"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="password_setup_token")


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
