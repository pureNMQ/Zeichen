"""The rebuildable file reference projection of a timeline revision."""

from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.orm import Session

from .markdown_refs import extract_markdown_refs
from .resource_refs import ResourceKind
from .timeline_models import TimelineFileReference, TimelineRevision


def file_reference_rows(entry_id: UUID, version: int, project_id: UUID, body: str | None) -> list[dict]:
    return [
        {"entry_id": entry_id, "version": version, "file_id": UUID(ref.identifier)}
        for ref in extract_markdown_refs(body or "", project_id) if ref.kind == ResourceKind.FILE
    ]


def append_revision(db: Session, revision: TimelineRevision) -> None:
    db.add(revision)
    db.flush()
    rows = file_reference_rows(revision.entry_id, revision.version, revision.project_id, revision.body)
    if rows:
        db.execute(insert(TimelineFileReference), rows)
