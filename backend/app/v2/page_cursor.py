"""Opaque keyset positions tied to one authorized view."""

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..errors import invalid_request
from .resource_refs import parse_uuid


def scope_key(*filters: Any) -> str:
    value = json.dumps(filters, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def encode_position(scope: str, position: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps([scope, position], separators=(",", ":")).encode()).decode()


def decode_position(scope: str, cursor: str | None) -> list[Any] | None:
    if cursor is None:
        return None
    try:
        if not 1 <= len(cursor) <= 512:
            raise ValueError
        key, position = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if key != scope or not isinstance(position, list):
            raise ValueError
        return position
    except (ValueError, TypeError, binascii.Error) as exc:
        raise invalid_request("游标无效或与当前筛选条件不匹配") from exc


def decode_time_position(scope: str, cursor: str | None) -> tuple[datetime, UUID] | None:
    position = decode_position(scope, cursor)
    if position is None:
        return None
    try:
        raw_time, raw_id = position
        cutoff = datetime.fromisoformat(raw_time)
        if cutoff.utcoffset() is None:
            raise ValueError
        return cutoff, parse_uuid(raw_id, "cursor.id")
    except (ValueError, TypeError) as exc:
        raise invalid_request("排序游标无效") from exc


def as_utc(value: datetime) -> datetime:
    # The SQLite dialect returns timezone-naive values from DateTime.
    return value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
