"""Retry-safe project mutations. Each command joins the caller's transaction."""

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from ..errors import conflict, invalid_request
from ..models.base import Base, CreatedAtMixin


class CommandReceipt(CreatedAtMixin, Base):
    __tablename__ = "v2_command_receipt"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("project.id"), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("user.id"), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    receipt: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


def execute_once(
    db: Session,
    *,
    project_id: UUID,
    actor_id: UUID,
    operation: str,
    request_id: UUID,
    payload: dict[str, Any],
    apply: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Authorize before calling. The callback may flush, but never commit.

    Payload is the normalized JSON command, including its target and version if
    applicable. Persist only a short public receipt, never content or credentials.
    An exception from apply must roll back the enclosing transaction.
    """
    if not 1 <= len(operation) <= 64:
        raise ValueError("operation must contain 1 to 64 characters")
    try:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise invalid_request("请求内容不能用于幂等校验") from exc
    fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
    key = (project_id, actor_id, operation, request_id)
    statement = {"postgresql": pg_insert, "sqlite": sqlite_insert}[db.get_bind().dialect.name]
    inserted = db.execute(
        statement(CommandReceipt)
        .values(
            project_id=project_id,
            actor_id=actor_id,
            operation=operation,
            request_id=request_id,
            fingerprint=fingerprint,
        )
        .on_conflict_do_nothing()
        .returning(CommandReceipt.request_id)
    ).scalar_one_or_none()
    row = db.get(CommandReceipt, key)
    if row is None:
        raise RuntimeError("command receipt missing after insert")
    if inserted is None:
        if row.fingerprint != fingerprint:
            raise conflict("请求标识已用于不同内容，请使用新标识")
        if row.receipt is None:
            raise RuntimeError("command receipt committed without an output")
        return row.receipt
    receipt = apply()
    row.receipt = receipt
    db.flush()
    return receipt
