"""Project-scoped resource identities shared by HTTP, MCP, and Markdown."""

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from ..errors import invalid_request


class ResourceKind(StrEnum):
    REQUIREMENT = "requirements"
    TASK = "tasks"
    WIKI = "wiki"
    FILE = "files"
    PERSON = "people"


_SHORT_CODES = {
    ResourceKind.REQUIREMENT: re.compile(r"REQ-[1-9][0-9]*"),
    ResourceKind.TASK: re.compile(r"(?:TASK-[1-9][0-9]*|REQ-[1-9][0-9]*-T[1-9][0-9]*)"),
    ResourceKind.WIKI: re.compile(r"(?:DOC|TERM)-[1-9][0-9]*"),
}


def parse_uuid(value: str, field: str) -> UUID:
    if isinstance(value, str) and len(value) == 36:
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value:
                return parsed
    raise invalid_request(f"{field} 必须是标准小写 UUID")


@dataclass(frozen=True, slots=True)
class ResourceRef:
    project_id: UUID
    kind: ResourceKind
    identifier: str

    def __post_init__(self) -> None:
        pattern = _SHORT_CODES.get(self.kind)
        if pattern is None:
            parse_uuid(self.identifier, "identifier")
        elif len(self.identifier) > (36 if self.kind == ResourceKind.TASK else 16) or pattern.fullmatch(self.identifier) is None:
            raise invalid_request("identifier 不符合该资源类型的短码格式")

    @property
    def path(self) -> str:
        return f"/projects/{self.project_id}/{self.kind.value}/{self.identifier}"

    @classmethod
    def from_markdown_href(cls, href: str) -> "ResourceRef | None":
        """Resolve only canonical site-relative paths; a fragment is presentation only."""
        if not href.startswith("/projects/") or any(c.isspace() or ord(c) < 32 for c in href):
            return None
        parts = urlsplit(href)
        segments = parts.path.split("/")
        if "?" in href.split("#", 1)[0] or len(segments) != 5:
            return None
        try:
            kind = ResourceKind(segments[3])
        except ValueError:
            return None
        return cls(parse_uuid(segments[2], "project_id"), kind, segments[4])
