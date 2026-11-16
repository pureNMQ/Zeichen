"""Bounded streaming to a local store addressed exclusively by project and file UUIDs."""

import codecs
import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO
from uuid import UUID

from ..config import get_settings
from ..errors import conflict, invalid_request

_PROBE_BYTES = 16 * 1024


def file_path(project_id: UUID, file_id: UUID) -> Path:
    return library_root() / str(project_id) / f"{file_id}.bin"


def library_root() -> Path:
    return Path(get_settings().attachment_storage_dir) / "library-v2"


def detect_media_type(head: bytes) -> str:
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"%PDF-", "application/pdf"),
    )
    for prefix, media_type in signatures:
        if head.startswith(prefix):
            return media_type
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        if head[8:12] in {b"avif", b"avis"}:
            return "image/avif"
        if head[8:12] in {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V "}:
            return "video/mp4"
    if head.startswith(b"\x1a\x45\xdf\xa3") and b"\x42\x82\x84webm" in head[:256]:
        return "video/webm"
    try:
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(head, final=False)
    except UnicodeDecodeError:
        return "application/octet-stream"
    if text and all(char.isprintable() or char in "\r\n\t" for char in text):
        return "text/plain"
    return "application/octet-stream"


def supports_preview(media_type: str) -> bool:
    return media_type in {
        "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
        "video/mp4", "video/webm", "application/pdf", "text/plain",
    }


class StagedFile:
    """Receive chunks while counting bytes, hashing, and buffering a small MIME probe."""

    def __init__(self, stream: BinaryIO, path: Path, max_bytes: int):
        self._stream = stream
        self._path = path
        self._max_bytes = max_bytes
        self._hash = hashlib.sha256()
        self._probe = bytearray()
        self._published: Path | None = None
        self.size = 0

    def write(self, chunk: bytes) -> None:
        if self.size + len(chunk) > self._max_bytes:
            raise conflict(f"文件超过单文件上限 ({self._max_bytes} 字节)")
        self._stream.write(chunk)
        self._hash.update(chunk)
        self._probe.extend(chunk[:max(0, _PROBE_BYTES - len(self._probe))])
        self.size += len(chunk)

    @property
    def sha256(self) -> str:
        return self._hash.hexdigest()

    @property
    def media_type(self) -> str:
        return detect_media_type(bytes(self._probe))

    def publish(self, project_id: UUID, file_id: UUID) -> None:
        if self.size == 0:
            raise invalid_request("文件内容为空")
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        final = file_path(project_id, file_id)
        final.parent.mkdir(exist_ok=True, parents=True)
        # Same-volume link is atomic and cannot replace existing bytes.
        os.link(self._path, final)
        self._published = final

    def discard_uncommitted_bytes(self) -> None:
        if self._published is not None:
            self._published.unlink(missing_ok=True)
            self._published = None


@contextmanager
def stage_file(*, byte_limit: int | None = None) -> Iterator[StagedFile]:
    scratch = library_root() / ".staging"
    scratch.mkdir(exist_ok=True, parents=True)
    stream = NamedTemporaryFile(dir=scratch, suffix=".part", delete=False)
    path = Path(stream.name)
    lock_fd = None
    try:
        if os.name == "posix":
            from fcntl import LOCK_EX, flock

            # Publish closes the stream before linking. Keep its lock until
            # the pathname is either published or removed.
            lock_fd = os.dup(stream.fileno())
            flock(lock_fd, LOCK_EX)
        limit = get_settings().file_library_max_file_bytes if byte_limit is None else byte_limit
        yield StagedFile(stream, path, limit)
    finally:
        try:
            stream.close()
            path.unlink(missing_ok=True)
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
