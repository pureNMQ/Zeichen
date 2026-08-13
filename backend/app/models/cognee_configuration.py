"""Workspace-scoped Cognee configuration managed by Zeichen administrators."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class CogneeConfiguration(IdMixin, TimestampMixin, Base):
    """The desired Cognee runtime configuration.

    Secrets are encrypted at rest and deliberately have no plaintext response
    representation.  ``pending_restart`` remains true until the restart
    coordinator has successfully applied this desired configuration.
    """

    __tablename__ = "cognee_configuration"

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("team.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    llm_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(256), nullable=False)
    llm_endpoint: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    llm_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_restart: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
