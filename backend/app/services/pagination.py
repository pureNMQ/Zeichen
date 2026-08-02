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


def encode_cursor(filters: dict, offset: int) -> str | None:
    if offset <= 0:
        return None
    payload = json.dumps({"o": offset, "h": _hash(filters)}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(filters: dict, cursor: str | None) -> int:
    """解出 offset;游标缺失 → 0;非法或跨条件 → invalid_request。"""
    if cursor is None:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, base64.binascii.Error):
        raise invalid_request("游标无效")
    if not isinstance(payload, dict) or payload.get("h") != _hash(filters):
        raise invalid_request("游标与筛选条件不匹配")
    offset = payload.get("o", 0)
    if not isinstance(offset, int) or offset < 0:
        raise invalid_request("游标无效")
    return offset


def page_result(items: list, offset: int, limit: int, filters: dict) -> dict:
    """包装一页结果:取 limit 条,有余量则带 next_cursor。"""
    next_offset = offset + len(items) if len(items) >= limit else None
    return {
        "items": items,
        "next_cursor": encode_cursor(filters, next_offset) if next_offset is not None else None,
    }
