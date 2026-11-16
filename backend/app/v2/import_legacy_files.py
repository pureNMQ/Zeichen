"""Copy project attachments to file-library storage without replacing bytes."""

import hashlib
import os
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Attachment
from .file_models import FileAssociation, ProjectFile
from .file_storage import detect_media_type, file_path

TARGETS = {"requirement": "requirements", "task": "tasks", "document": "wiki", "project": "project"}


def _digest(stream: BinaryIO, output: BinaryIO | None = None) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        digest.update(chunk)
        if output:
            output.write(chunk)
    return size, digest.hexdigest()


def _copy(source: Path, destination: Path) -> tuple[int, str, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as stream:
        kind = detect_media_type(stream.read(16 * 1024))
        stream.seek(0)
        with NamedTemporaryFile(dir=destination.parent, suffix=".import", delete=False) as staged:
            scratch = Path(staged.name)
            try:
                size, digest = _digest(stream, staged)
                staged.flush()
                os.fsync(staged.fileno())
                staged.close()
                if size > 0:
                    try:
                        os.link(scratch, destination)
                    except FileExistsError:
                        with destination.open("rb") as existing:
                            if _digest(existing) != (size, digest):
                                raise RuntimeError(f"File import found mismatched target bytes: {destination.name}")
            finally:
                scratch.unlink(missing_ok=True)
    return size, digest, kind


def import_files(db: Session, old_storage: Path) -> tuple[dict[str, int], list[dict]]:
    counts: Counter[str] = Counter()
    exceptions: list[dict] = []
    for attachment in db.scalars(select(Attachment).order_by(Attachment.id)).yield_per(100):
        if attachment.project_id is None:
            counts["workspace_files_left_in_legacy_storage"] += 1
            continue
        project_id, file_id = attachment.project_id, attachment.id
        source = old_storage / str(project_id) / f"{file_id}.bin"
        destination = file_path(project_id, file_id)

        def note(reason: str) -> None:
            exceptions.append({"id": str(file_id), "project_id": str(project_id),
                               "target_kind": attachment.target_type, "target_id": attachment.target_id,
                               "reason": reason})

        if not source.is_file() or source.is_symlink():
            note("legacy_bytes_missing")
            continue
        copied_size, digest, kind = _copy(source, destination)
        if copied_size == 0:
            note("legacy_empty_file")
            continue
        if attachment.size != copied_size:
            note("legacy_size_mismatch")
        row = db.get(ProjectFile, (project_id, file_id))
        if row is not None:
            if (row.size, row.sha256) != (copied_size, digest):
                raise RuntimeError(f"Legacy file identity collision: {file_id}")
            counts["already_imported"] += 1
        else:
            db.add(ProjectFile(
                project_id=project_id, id=file_id, name=attachment.file_name, media_type=kind, size=copied_size,
                sha256=digest, created_by=attachment.created_by, created_at=attachment.created_at,
                updated_at=attachment.updated_at, deleted_at=attachment.deleted_at,
            ))
            db.flush()
            counts["files_imported"] += 1
        if attachment.deleted_at is not None:
            note("legacy_file_delete_origin_unknown")
        target_kind = TARGETS.get(attachment.target_type)
        if target_kind is None:
            note("legacy_file_association_retained_in_source")
            continue
        key = (project_id, file_id, target_kind, attachment.target_id)
        if db.get(FileAssociation, key) is None:
            db.add(FileAssociation(project_id=project_id, file_id=file_id,
                                   target_kind=target_kind, target_id=attachment.target_id,
                                   created_by=attachment.created_by, created_at=attachment.created_at))
            counts["associations_imported"] += 1
    db.flush()
    return dict(counts), exceptions
