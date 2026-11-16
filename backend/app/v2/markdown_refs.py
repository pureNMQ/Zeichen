"""Extract stable resource identities from CommonMark link and image tokens."""

from uuid import UUID

from markdown_it import MarkdownIt

from ..errors import AppError
from .resource_refs import ResourceRef

_MARKDOWN = MarkdownIt("commonmark").enable("table")


def extract_markdown_refs(body: str, project_id: UUID) -> frozenset[ResourceRef]:
    """Index same-project links, independent of display text and fragments."""
    targets: set[ResourceRef] = set()
    for block in _MARKDOWN.parse(body):
        if block.type != "inline":
            continue
        for token in block.children or ():
            attribute = {"link_open": "href", "image": "src"}.get(token.type)
            if attribute is None:
                continue
            href = token.attrGet(attribute)
            if not isinstance(href, str):
                continue
            try:
                ref = ResourceRef.from_markdown_href(href)
            except AppError:
                continue
            if ref is not None and ref.project_id == project_id:
                targets.add(ref)
    return frozenset(targets)
