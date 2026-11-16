"""Validation shared by REST services and MCP tools for short descriptions.

需求/任务描述仅支持简短纯文本(REQ-2):可安全剥离的 Markdown 记号规范化
为纯文本;raw HTML 标签与 Markdown 图片不可安全剥离,明确报错。
长度上限作用于规范化后的最终文本,与 DB CHECK、前端 maxLength 一致。
"""

import re

from ..errors import invalid_request

SHORT_DESCRIPTION_MAX_LENGTH = 512

# raw HTML 标签(如 <div>、</script>、<br/>):富文本载体 → 拒绝。
# 要求标签名以字母开头,避免把 "3 < 5" 这类比较文本误判为 HTML。
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^>]*)?/?>")
# Markdown 图片 ![alt](url):嵌入外部资源,不可安全剥离 → 拒绝。
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# 链接 [text](url) → text(URL 丢弃,文字保留)。
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# 行内代码 `code` → code。
_MD_CODE_RE = re.compile(r"`([^`]+)`")
# 成对强调剥离。双下划线与单下划线沿用 CommonMark 词内禁用规则:
# 开/闭记号必须紧邻非文字字符,保证 user_profile_service 等词内下划线原样保留。
_MD_STRONG_RE = re.compile(r"\*\*([^*]+)\*\*")
_MD_EM_RE = re.compile(r"\*([^*]+)\*")
_MD_UNDERLINE_STRONG_RE = re.compile(r"(?<!\w)__([^_]+)__(?!\w)")
_MD_UNDERLINE_EM_RE = re.compile(r"(?<!\w)_([^_]+)_(?!\w)")
_MD_STRIKE_RE = re.compile(r"~~([^~]+)~~")


def _strip_markdown(text: str) -> str:
    """把可安全剥离的 Markdown 记号规范化为纯文本,其余原样保留。"""
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _MD_CODE_RE.sub(r"\1", text)
    text = _MD_STRONG_RE.sub(r"\1", text)
    text = _MD_EM_RE.sub(r"\1", text)
    text = _MD_UNDERLINE_STRONG_RE.sub(r"\1", text)
    text = _MD_UNDERLINE_EM_RE.sub(r"\1", text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    return text


def normalize_short_description(value: str | None) -> str | None:
    """Return a trimmed, single-line plain-text description or raise a domain error."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid_request("描述必须是字符串")
    result = value.strip()
    if not result:
        return None
    if "\n" in result or "\r" in result:
        raise invalid_request("描述只能是单行纯文本")
    if _HTML_TAG_RE.search(result):
        raise invalid_request("描述不支持 HTML 标签,请使用纯文本")
    if _MD_IMAGE_RE.search(result):
        raise invalid_request("描述不支持 Markdown 图片,请使用纯文本")
    result = _strip_markdown(result).strip()
    if not result:
        return None
    if len(result) > SHORT_DESCRIPTION_MAX_LENGTH:
        raise invalid_request(f"描述不能超过 {SHORT_DESCRIPTION_MAX_LENGTH} 个字符")
    return result
