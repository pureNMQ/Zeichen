"""cursor 不透明分页(规格书 §4.1):返回 {items, next_cursor}。

cursor = base64url({o: offset, h: 筛选条件哈希});条件哈希防止跨筛选
条件复用游标;解析失败或哈希不匹配 → invalid_request。
"""

import base64
import hashlib
import json

from ..errors import invalid_request

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _hash(filters: dict) -> str:
    payload = json.dumps(filters, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def encode_cursor(filters: dict, offset: int, limit: int | None = None) -> str | None:
    if offset <= 0:
        return None
    payload: dict = {"o": offset, "h": _hash(filters)}
    if limit is not None:
        payload["l"] = limit
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def decode_cursor(filters: dict, cursor: str | None) -> int:
    """解出 offset;游标缺失 → 0;非法或跨条件 → invalid_request。"""
    return _decode(filters, cursor)["o"]


def decode_cursor_page(filters: dict, cursor: str | None, limit: int | None = None) -> tuple[int, int]:
    """解出 (offset, page_size);游标携带页大小且调用方未显式给 limit 时沿用游标页大小。"""
    payload = _decode(filters, cursor)
    offset = payload["o"]
    if limit is None:
        encoded = payload.get("l")
        if isinstance(encoded, int) and encoded > 0:
            limit = encoded
    return offset, limit if limit is not None else DEFAULT_PAGE_SIZE


def _decode(filters: dict, cursor: str | None) -> dict:
    if cursor is None:
        return {"o": 0}
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, base64.binascii.Error):
        raise invalid_request("游标无效")
    if not isinstance(payload, dict) or payload.get("h") != _hash(filters):
        raise invalid_request("游标与筛选条件不匹配")
    offset = payload.get("o", 0)
    if not isinstance(offset, int) or offset < 0:
        raise invalid_request("游标无效")
    return payload


def page_result(items: list, offset: int, limit: int, filters: dict) -> dict:
    """包装一页结果:取 limit 条,有余量则带 next_cursor(游标携带页大小)。"""
    next_offset = offset + len(items) if len(items) >= limit else None
    return {
        "items": items,
        "next_cursor": encode_cursor(filters, next_offset, limit) if next_offset is not None else None,
    }
