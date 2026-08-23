"""Validation shared by REST services and MCP tools for short descriptions."""

from ..errors import invalid_request

SHORT_DESCRIPTION_MAX_LENGTH = 512


def normalize_short_description(value: str | None) -> str | None:
    """Return a trimmed, single-line description or raise a domain error."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_request("描述必须是字符串")
    result = value.strip()
    if not result:
        return None
    if "\n" in result or "\r" in result:
        raise invalid_request("描述只能是单行纯文本")
    if len(result) > SHORT_DESCRIPTION_MAX_LENGTH:
        raise invalid_request(f"描述不能超过 {SHORT_DESCRIPTION_MAX_LENGTH} 个字符")
    return result
