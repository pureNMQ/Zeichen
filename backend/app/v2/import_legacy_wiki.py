"""Replay v1 Wiki documents and version snapshots without touching source rows."""

import re
from collections import Counter, defaultdict
from html import escape
from uuid import UUID
from urllib.parse import quote, urlsplit

from markdown_it import MarkdownIt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import DocLink, Document, DocumentVersion
from ..services.documents import merge_metadata, split_frontmatter
from .resource_refs import ResourceKind, ResourceRef
from .file_models import ProjectFile
from .wiki import store_version_references
from .wiki_models import Wiki, WikiVersion

_MARKDOWN = MarkdownIt("commonmark").enable("table")
_WIKI_LINK = re.compile(r"(?<![\\!])\[\[([^\[\]\n|]+)(?:\|([^\[\]\n]+))?\]\](?![\[(])")
_INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.DOTALL)
_SHORT_CODE = re.compile(r"(?:DOC|TERM)-[1-9]\d*", re.IGNORECASE)
_ATTACHMENT_URL = re.compile(
    r"(?<=\])\(<?((?:https?://[^/\s<>]+)?/api/attachments/([0-9a-f-]{36})/download)>?\)"
)
_ATTRIBUTES = {"summary", "doc_kind", "tags", "aliases"}


def _content(raw: str | None, stored: dict | None) -> tuple[dict, dict, set[str]]:
    attributes, body = split_frontmatter(raw)
    effective = merge_metadata(stored if isinstance(stored, dict) else None, attributes)
    tags = effective.get("tags")
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, list):
        tags = []
    outcome = {
        "body": body,
        "summary": effective.get("summary") if isinstance(effective.get("summary"), str) else None,
        "category": effective.get("doc_kind") if isinstance(effective.get("doc_kind"), str) else None,
        "tags": list(dict.fromkeys(tag.strip() for tag in tags if isinstance(tag, str) and tag.strip())),
    }
    unknown = {str(key) for key in effective if key not in _ATTRIBUTES}
    if stored is not None and not isinstance(stored, dict):
        unknown.add("metadata_not_object")
    return outcome, effective, unknown


def _convert_links(body: str, project_id: UUID, resolve, report, files: set[str]) -> str:
    lines = body.splitlines(keepends=True)
    ends = [0]
    for line in lines:
        ends.append(ends[-1] + len(line))
    protected = [
        (ends[block.map[0]], ends[block.map[1]])
        for block in _MARKDOWN.parse(body)
        if block.type in {"fence", "code_block", "html_block"} and block.map is not None
    ]
    protected.extend(match.span() for match in _INLINE_CODE.finditer(body))

    def protected_link(match: re.Match) -> bool:
        return any(start <= match.start() < stop for start, stop in protected)

    def replace(match: re.Match) -> str:
        if protected_link(match):
            return match.group()
        target, _, section = match[1].partition("#")
        label = (match[2] or target).strip()
        code = resolve(target.strip(), label if match[2] else None, section.strip() or None)
        if code is None:
            report("unresolved_wiki_link", target.strip())
            return match.group()
        path = ResourceRef(project_id, ResourceKind.WIKI, code).path
        if section.strip():
            path += "#" + quote(section.strip(), safe="-_")
        label = re.sub(r"([\\\[\]_*~`])", r"\\\1", escape(label))
        return f"[{label}](<{path}>)"

    base = urlsplit(get_settings().web_base_url)

    def replace_attachment(match: re.Match) -> str:
        if protected_link(match):
            return match.group()
        parsed = urlsplit(match[1])
        if parsed.netloc and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            return match.group()
        if match[2] not in files:
            report("unresolved_attachment_link", match[2])
            return match.group()
        path = ResourceRef(project_id, ResourceKind.FILE, match[2]).path
        return f"(<{path}>)"

    # Apply a single combined scan so the code-block offsets refer to original bytes.
    replacements = [(match.start(), match.end(), replace(match)) for match in _WIKI_LINK.finditer(body)]
    replacements.extend((match.start(), match.end(), replace_attachment(match)) for match in _ATTACHMENT_URL.finditer(body))
    for start, stop, content in sorted(replacements, reverse=True):
        body = body[:start] + content + body[stop:]
    return body


def import_wiki(db: Session) -> tuple[dict[str, int], list[dict]]:
    """Import documents, then link parents and index each newly inserted version."""
    counts: Counter[str] = Counter()
    exceptions: list[dict] = []
    projects = db.scalars(select(Document.project_id).distinct().order_by(Document.project_id)).all()
    for project_id in projects:
        documents = db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.code)).all()
        codes = {doc.code for doc in documents}
        files = {str(value) for value in db.scalars(select(ProjectFile.id).where(ProjectFile.project_id == project_id))}
        by_title: dict[str, set[str]] = defaultdict(set)
        by_alias: dict[str, set[str]] = defaultdict(set)
        for doc in documents:
            _, meta, _ = _content(doc.content, doc.doc_metadata)
            if doc.deleted_at is None:
                by_title[doc.title].add(doc.code)
                aliases = meta.get("aliases") or []
                if isinstance(aliases, str):
                    aliases = aliases.split(",")
                if isinstance(aliases, list):
                    for alias in aliases:
                        if isinstance(alias, str) and alias.strip():
                            by_alias[alias.strip()].add(doc.code)
        saved_links = {
            (row.from_code, row.raw_text, row.display_text, row.section): row.to_code
            for row in db.scalars(select(DocLink).where(DocLink.project_id == project_id))
        }
        parents: list[tuple[Wiki, str]] = []
        for doc in documents:
            live = db.get(Wiki, (project_id, doc.code))
            if live is not None:
                counts["already_imported"] += 1
                continue

            def note(reason: str, value: str, version: int | None = None) -> None:
                exceptions.append({"project_id": str(project_id), "code": doc.code, "version": version,
                                   "reason": reason, "value": value})

            def resolve(target: str, label: str | None, section: str | None, *, current: bool) -> str | None:
                if _SHORT_CODE.fullmatch(target):
                    return target.upper() if target.upper() in codes else None
                if not current:
                    return None
                key = (doc.code, target, label, section)
                if key in saved_links:
                    code = saved_links[key]
                    return code if code in codes else None
                choices = by_title.get(target) or by_alias.get(target) or set()
                return next(iter(choices)) if len(choices) == 1 else None

            fields, effective, unknown = _content(doc.content, doc.doc_metadata)
            for field in sorted(unknown):
                note("legacy_attribute_retained_in_source", field)
            fields["body"] = _convert_links(fields["body"], project_id, lambda *args: resolve(*args, current=True), note, files)
            versions = db.scalars(select(DocumentVersion).where(
                DocumentVersion.project_id == project_id, DocumentVersion.document_id == doc.code,
            ).order_by(DocumentVersion.version_no)).all()
            latest = versions[-1] if versions else None
            same = bool(latest and latest.title == doc.title and (doc.content or "") == latest.content
                        and _content(latest.content, latest.doc_metadata)[1] == effective)
            live_version = (latest.version_no if latest else 0) + (0 if same else 1)
            live = Wiki(project_id=project_id, code=doc.code, title=doc.title, version_no=live_version,
                        created_by=doc.created_by, created_at=doc.created_at, updated_at=doc.updated_at,
                        deleted_at=doc.deleted_at, **fields)
            db.add(live)
            db.flush()
            if doc.parent_id in codes:
                parents.append((live, doc.parent_id))
            elif doc.parent_id is not None:
                note("legacy_parent_missing", doc.parent_id)

            for version in versions:
                snapshot_fields, _, version_unknown = _content(version.content, version.doc_metadata)
                for field in sorted(version_unknown):
                    note("legacy_attribute_retained_in_source", field, version.version_no)
                if same and version is latest:
                    snapshot_fields = fields
                else:
                    snapshot_fields["body"] = _convert_links(
                        snapshot_fields["body"], project_id, lambda *args: resolve(*args, current=False),
                        lambda reason, value: note(reason, value, version.version_no), files,
                    )
                snapshot = WikiVersion(id=version.id, project_id=project_id, wiki_code=doc.code,
                                       title=version.title, version_no=version.version_no,
                                       created_by=version.created_by, created_at=version.created_at, **snapshot_fields)
                db.add(snapshot)
                db.flush()
                store_version_references(db, snapshot)
                counts["versions_imported"] += 1
            if not same:
                note("legacy_live_state_snapshot", str(live_version))
                snapshot = WikiVersion(project_id=project_id, wiki_code=doc.code, title=doc.title,
                                       version_no=live_version, created_at=doc.updated_at, **fields)
                db.add(snapshot)
                db.flush()
                store_version_references(db, snapshot)
                counts["versions_imported"] += 1
            counts["documents_imported"] += 1
        for wiki, parent in parents:
            db.execute(update(Wiki).where(Wiki.project_id == project_id, Wiki.code == wiki.code)
                       .values(parent_id=parent, updated_at=wiki.updated_at))
        db.flush()
    return dict(counts), exceptions
