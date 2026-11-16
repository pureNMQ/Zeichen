"""One-shot v2 maintenance. Only expired grants and abandoned staging parts."""

import argparse
import errno
import json
import os
import re
import stat
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..v2.file_models import FileGrant, FileUploadGrant
from ..v2.file_storage import library_root


_LOCK_ID = int.from_bytes(b"ZCHv2mnt", "big")
_PART_NAME = re.compile(r"tmp[a-z0-9_]{8}\.part", re.ASCII)


@dataclass
class Counts:
    expired_read_grants_deleted: int = 0
    expired_upload_grants_deleted: int = 0
    staging_scanned: int = 0
    stale_parts_deleted: int = 0
    locked_parts_skipped: int = 0
    staging_limit_reached: bool = False


def _try_lock(db: Session) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        raise RuntimeError("v2 maintenance requires the PostgreSQL deployment database")
    db.execute(text("SET LOCAL lock_timeout = '10s'"))
    db.execute(text("SET LOCAL statement_timeout = '60s'"))
    return bool(db.scalar(select(func.pg_try_advisory_xact_lock(_LOCK_ID))))


def delete_expired_grants(
    db: Session, grant: type[FileGrant] | type[FileUploadGrant], cutoff: datetime, limit: int,
) -> int:
    expired = select(grant.digest).where(grant.expires_at <= cutoff).order_by(
        grant.expires_at, grant.digest,
    ).limit(limit)
    deleted = db.scalars(
        delete(grant)
        .where(grant.digest.in_(expired), grant.expires_at <= cutoff)
        .returning(grant.digest)
    ).all()
    return len(deleted)


def _prune_part(staging_fd: int, name: str, cutoff: float, counts: Counts) -> None:
    from fcntl import LOCK_EX, LOCK_NB, flock

    try:
        before = os.stat(name, dir_fd=staging_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_mtime > cutoff:
            return
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=staging_fd)
    except FileNotFoundError:
        return
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return
        raise
    try:
        try:
            flock(fd, LOCK_EX | LOCK_NB)
        except BlockingIOError:
            counts.locked_parts_skipped += 1
            return
        opened = os.fstat(fd)
        current = os.stat(name, dir_fd=staging_fd, follow_symlinks=False)
        if (
            stat.S_ISREG(opened.st_mode) and opened.st_mtime <= cutoff
            and (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
            and current.st_mtime <= cutoff
        ):
            os.unlink(name, dir_fd=staging_fd)
            counts.stale_parts_deleted += 1
    except FileNotFoundError:
        pass  # A publisher finished and removed its staging name in the meantime.
    finally:
        os.close(fd)


def prune_staging(root: Path, cutoff: datetime, *, limit: int, scan_limit: int, counts: Counts) -> None:
    """Bound unlinks and scanning; follow neither symlinks nor subdirectories."""
    if os.name != "posix":
        raise RuntimeError("v2 staging maintenance requires POSIX file locks")
    if not root.parent.is_dir():
        raise FileNotFoundError(errno.ENOENT, "configured file volume is missing")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    cutoff_seconds = cutoff.timestamp()
    try:
        root_fd = os.open(root, directory_flags)
    except FileNotFoundError:
        return  # Library has never received an upload.
    try:
        try:
            staging_fd = os.open(".staging", directory_flags, dir_fd=root_fd)
        except FileNotFoundError:
            return
        try:
            with os.scandir(staging_fd) as entries:
                for entry in entries:
                    if counts.staging_scanned >= scan_limit or counts.stale_parts_deleted >= limit:
                        counts.staging_limit_reached = True
                        break
                    counts.staging_scanned += 1
                    if _PART_NAME.fullmatch(entry.name):
                        _prune_part(staging_fd, entry.name, cutoff_seconds, counts)
        finally:
            os.close(staging_fd)
    finally:
        os.close(root_fd)


def _bounded(minimum: int, maximum: int):
    def parse(raw: str) -> int:
        value = int(raw)
        if not minimum <= value <= maximum:
            raise argparse.ArgumentTypeError(f"expected {minimum} to {maximum}")
        return value

    return parse


def _session() -> Session:
    from ..db import SessionLocal

    return SessionLocal()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stale-hours", type=_bounded(1, 720), default=24)
    parser.add_argument("--max-grants", type=_bounded(1, 10_000), default=2_000, help="maximum per grant type")
    parser.add_argument("--max-parts", type=_bounded(1, 1_000), default=500)
    parser.add_argument("--scan-limit", type=_bounded(1, 50_000), default=10_000)
    args = parser.parse_args(argv)
    started = datetime.now(UTC)
    clock = time.monotonic()
    counts = Counts()
    status = "success"
    phase = "lock"
    error: dict = {}
    try:
        with _session() as db:
            if not _try_lock(db):
                status = "skipped_locked"
            else:
                phase = "expired_read_grants"
                read_grants = delete_expired_grants(db, FileGrant, started, args.max_grants)
                phase = "expired_upload_grants"
                upload_grants = delete_expired_grants(db, FileUploadGrant, started, args.max_grants)
                phase = "staging"
                prune_staging(
                    library_root(), started - timedelta(hours=args.stale_hours),
                    limit=args.max_parts, scan_limit=args.scan_limit, counts=counts,
                )
                phase = "commit"
                db.commit()
                counts.expired_read_grants_deleted = read_grants
                counts.expired_upload_grants_deleted = upload_grants
    except Exception as exc:
        status = "failed"
        # Driver errors can contain SQL and credentials; keep output suitable
        # for the journal and preserve a useful stage/type/errno.
        error = {"phase": phase, "error_type": type(exc).__name__}
        if isinstance(exc, OSError) and exc.errno is not None:
            error["errno"] = exc.errno
    print(json.dumps({
        "event": "zeichen_v2_maintenance", "status": status,
        "started_at": started.isoformat(), "elapsed_ms": round((time.monotonic() - clock) * 1000),
        **asdict(counts), **error,
    }), flush=True)
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
