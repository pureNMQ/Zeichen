"""Scoped, immutable project file metadata and revocable short-lived reads."""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select, tuple_
from sqlalchemy.orm import Session, aliased

from ..config import get_settings
from ..errors import conflict, invalid_request, not_found
from ..models import ApiKey, Project, User
from ..services.pagination import MAX_PAGE_SIZE, decode_cursor, encode_cursor
from ..services.permissions import get_accessible_project
from .commands import execute_once
from .file_models import FileGrant, FileUploadGrant, ProjectFile
from .file_storage import StagedFile, file_path, supports_preview
from .resource_refs import ResourceKind, ResourceRef

TRANSFER_PATH = "/api/v2/file-transfers"
_GRANT_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class FileState(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _transfer_url(project_id: UUID, item_id: UUID, token: str) -> str:
    base = get_settings().web_base_url.rstrip("/")
    origin = urlsplit(base)
    local = origin.hostname in {"localhost", "127.0.0.1", "::1"}
    if not origin.hostname or origin.username is not None or origin.path or origin.query or origin.fragment or not (
        origin.scheme == "https" or (local and origin.scheme == "http")
    ):
        raise conflict("文件授权需要配置 HTTPS 公网地址")
    return f"{base}{TRANSFER_PATH}/{project_id}/{item_id}?grant={token}"


def _digest(token: str) -> str:
    if not _GRANT_TOKEN.fullmatch(token):
        raise not_found("文件授权不存在或已失效")
    return hashlib.sha256(token.encode()).hexdigest()


def _expires_at() -> datetime:
    return _now() + timedelta(seconds=get_settings().file_library_grant_ttl_seconds)


def require_file_access(db: Session, actor_id: UUID, project_id: UUID, *, edit: bool = False) -> User:
    actor = db.get(User, actor_id)
    if actor is None or actor.deleted_at is not None:
        raise not_found("项目不存在或无访问权限")
    get_accessible_project(db, actor_id, project_id, min_level="editor" if edit else "viewer")
    return actor


def _active_key(db: Session, actor_id: UUID, key_id: UUID) -> bool:
    return db.scalar(select(ApiKey.id).where(
        ApiKey.user_id == actor_id, ApiKey.id == key_id, ApiKey.revoked_at.is_(None),
    )) is not None


def _file(db: Session, project_id: UUID, file_id: UUID, state: FileState, *, lock: bool = False) -> ProjectFile:
    statement = select(ProjectFile).where(ProjectFile.project_id == project_id, ProjectFile.id == file_id)
    if state == FileState.ACTIVE:
        statement = statement.where(ProjectFile.deleted_at.is_(None))
    else:
        statement = statement.where(ProjectFile.deleted_at.is_not(None))
    obj = db.scalar(statement.with_for_update() if lock else statement)
    if obj is None:
        raise not_found("文件不存在或不可用")
    return obj


def get_file(db: Session, actor_id: UUID, project_id: UUID, file_id: UUID) -> ProjectFile:
    require_file_access(db, actor_id, project_id)
    return _file(db, project_id, file_id, FileState.ACTIVE)


def _file_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 255 or name in {".", ".."} or any(
        char in "/\\" or not char.isprintable() for char in name
    ):
        raise invalid_request("文件名须为 1 到 255 个可显示字符，不能包含路径")
    return name


def _capacity(db: Session, project_id: UUID, proposed_bytes: int) -> None:
    # Serialize quota checks per project. Soft-deleted bytes use the same storage.
    if db.scalar(select(Project.id).where(Project.id == project_id, Project.deleted_at.is_(None)).with_for_update()) is None:
        raise not_found("项目不存在或无访问权限")
    used = db.scalar(select(func.coalesce(func.sum(ProjectFile.size), 0)).where(ProjectFile.project_id == project_id))
    if used + proposed_bytes > get_settings().file_library_project_quota_bytes:
        raise conflict("项目文件配额不足")


def store_file(
    db: Session, actor_id: UUID, project_id: UUID, *, name: str, request_id: UUID, staged: StagedFile,
) -> dict:
    require_file_access(db, actor_id, project_id, edit=True)
    name = _file_name(name)
    if not staged.size:
        raise invalid_request("文件内容为空")

    def apply() -> dict:
        _capacity(db, project_id, staged.size)
        row = ProjectFile(
            project_id=project_id, id=uuid4(), name=name, size=staged.size, media_type=staged.media_type,
            sha256=staged.sha256, created_by=actor_id,
        )
        db.add(row)
        db.flush()
        staged.publish(project_id, row.id)
        return file_summary(row)

    return execute_once(
        db, project_id=project_id, actor_id=actor_id, operation="files.upload", request_id=request_id,
        payload={"name": name, "size": staged.size, "sha256": staged.sha256}, apply=apply,
    )


def file_summary(row: ProjectFile, *, detail: bool = False) -> dict:
    ref = ResourceRef(row.project_id, ResourceKind.FILE, str(row.id))
    result = {
        "id": str(row.id), "project_id": str(row.project_id), "name": row.name,
        "media_type": row.media_type, "size": row.size, "href": ref.path,
        "download_href": f"/api/v2{ref.path}/content" if row.deleted_at is None else None,
        "preview_href": (f"/api/v2{ref.path}/content?inline=true"
                         if row.deleted_at is None and supports_preview(row.media_type) else None),
    }
    if detail:
        result.update(sha256=row.sha256, created_at=row.created_at.isoformat(),
                      created_by=str(row.created_by) if row.created_by else None,
                      deleted_at=row.deleted_at.isoformat() if row.deleted_at else None)
    return result


def _cursor_id(filters: dict, cursor: str) -> UUID:
    # The common cursor currently encodes an integer. UUID-as-integer stores the anchor
    # without offset reads; project scope is still checked in the lookup below.
    raw = decode_cursor(filters, cursor)
    if not 0 < raw < 2 ** 128:
        raise invalid_request("游标无效")
    return UUID(int=raw)


def list_files(
    db: Session, actor_id: UUID, project_id: UUID, *, query: str = "", media_type: str | None = None,
    uploader_id: UUID | None = None, images_only: bool = False, state: FileState = FileState.ACTIVE,
    cursor: str | None = None, limit: int = 20,
) -> dict:
    require_file_access(db, actor_id, project_id, edit=state == FileState.DELETED)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise invalid_request(f"limit 必须在 1..{MAX_PAGE_SIZE} 之间")
    query = query.strip()
    filters = {"view": "files", "project_id": str(project_id), "actor_id": str(actor_id), "q": query,
               "media_type": media_type, "uploader": str(uploader_id) if uploader_id else None,
               "images_only": images_only, "state": state, "limit": limit}
    statement = select(ProjectFile).where(ProjectFile.project_id == project_id)
    if state == FileState.ACTIVE:
        statement = statement.where(ProjectFile.deleted_at.is_(None))
    else:
        statement = statement.where(ProjectFile.deleted_at.is_not(None))
    if query:
        statement = statement.where(ProjectFile.name.icontains(query, autoescape=True))
    if media_type is not None:
        statement = statement.where(ProjectFile.media_type == media_type)
    if images_only:
        statement = statement.where(ProjectFile.media_type.startswith("image/"))
    if uploader_id is not None:
        statement = statement.where(ProjectFile.created_by == uploader_id)
    if cursor is not None:
        before_id = _cursor_id(filters, cursor)
        anchor = aliased(ProjectFile)
        statement = statement.join(anchor, and_(anchor.project_id == project_id, anchor.id == before_id)).where(
            tuple_(ProjectFile.created_at, ProjectFile.id) < tuple_(anchor.created_at, anchor.id),
        )
    rows = db.scalars(statement.order_by(ProjectFile.created_at.desc(), ProjectFile.id.desc()).limit(limit + 1)).all()
    return {
        "items": [file_summary(row) for row in rows[:limit]],
        "next_cursor": encode_cursor(filters, rows[limit - 1].id.int) if len(rows) > limit else None,
    }


def rename_file(db: Session, actor_id: UUID, project_id: UUID, file_id: UUID, name: str) -> ProjectFile:
    require_file_access(db, actor_id, project_id, edit=True)
    row = _file(db, project_id, file_id, FileState.ACTIVE, lock=True)
    row.name = _file_name(name)
    db.flush()
    return row


def delete_file(db: Session, actor_id: UUID, project_id: UUID, file_id: UUID) -> None:
    require_file_access(db, actor_id, project_id, edit=True)
    row = _file(db, project_id, file_id, FileState.ACTIVE, lock=True)
    row.deleted_at = _now()
    row.deleted_by = actor_id
    db.execute(delete(FileGrant).where(FileGrant.project_id == project_id, FileGrant.file_id == file_id))
    db.flush()


def restore_file(db: Session, actor_id: UUID, project_id: UUID, file_id: UUID) -> ProjectFile:
    require_file_access(db, actor_id, project_id, edit=True)
    row = _file(db, project_id, file_id, FileState.DELETED, lock=True)
    if not file_path(project_id, file_id).is_file():
        raise conflict("原文件字节缺失，暂不能恢复")
    row.deleted_at = None
    row.deleted_by = None
    db.flush()
    return row


def issue_read_grant(
    db: Session, actor_id: UUID, project_id: UUID, file_id: UUID, *, api_key_id: UUID | None, inline: bool,
) -> dict:
    actor = require_file_access(db, actor_id, project_id)
    if actor.is_agent and (api_key_id is None or not _active_key(db, actor_id, api_key_id)):
        raise not_found("文件不存在或不可用")
    row = _file(db, project_id, file_id, FileState.ACTIVE, lock=True)
    token = secrets.token_urlsafe(32)
    access_url = _transfer_url(project_id, file_id, token)
    expires_at = _expires_at()
    db.add(FileGrant(digest=_digest(token), project_id=project_id,
                     file_id=file_id, actor_id=actor_id, api_key_id=api_key_id, expires_at=expires_at, inline=inline))
    db.flush()
    return {**file_summary(row), "access_url": access_url,
            "expires_at": expires_at.isoformat()}


def redeem_read_grant(db: Session, project_id: UUID, file_id: UUID, token: str) -> tuple[ProjectFile, bool]:
    grant = db.scalar(select(FileGrant).where(
        FileGrant.digest == _digest(token), FileGrant.project_id == project_id,
        FileGrant.file_id == file_id, FileGrant.expires_at > _now(),
    ))
    if grant is None:
        raise not_found("文件授权不存在或已失效")
    actor = require_file_access(db, grant.actor_id, project_id)
    if actor.is_agent and (grant.api_key_id is None or not _active_key(db, actor.id, grant.api_key_id)):
        raise not_found("文件授权不存在或已失效")
    return _file(db, project_id, file_id, FileState.ACTIVE), grant.inline


def issue_upload_grant(
    db: Session, actor_id: UUID, project_id: UUID, *, api_key_id: UUID, name: str, size: int,
) -> dict:
    actor = require_file_access(db, actor_id, project_id, edit=True)
    if not actor.is_agent or not _active_key(db, actor_id, api_key_id):
        raise not_found("文件授权不存在或已失效")
    if size < 1:
        raise invalid_request("上传字节数必须大于零")
    maximum = get_settings().file_library_max_file_bytes
    if size > maximum:
        raise conflict(f"文件超过单文件上限 ({maximum} 字节)")
    name = _file_name(name)
    token = secrets.token_urlsafe(32)
    upload_id = uuid4()
    upload_url = _transfer_url(project_id, upload_id, token)
    expires_at = _expires_at()
    db.add(FileUploadGrant(id=upload_id, project_id=project_id, actor_id=actor_id,
                           api_key_id=api_key_id, digest=_digest(token), name=name,
                           expected_size=size, expires_at=expires_at))
    db.flush()
    return {"project_id": str(project_id), "upload_id": str(upload_id), "upload_url": upload_url,
            "expires_at": expires_at.isoformat(), "method": "PUT", "content_length": size}


def _upload_grant(db: Session, project_id: UUID, upload_id: UUID, token: str) -> FileUploadGrant:
    grant = db.scalar(select(FileUploadGrant).where(
        FileUploadGrant.id == upload_id, FileUploadGrant.project_id == project_id,
        FileUploadGrant.digest == _digest(token), FileUploadGrant.expires_at > _now(),
    ))
    if grant is None:
        raise not_found("文件授权不存在或已失效")
    if not _active_key(db, grant.actor_id, grant.api_key_id):
        raise not_found("文件授权不存在或已失效")
    require_file_access(db, grant.actor_id, project_id, edit=True)
    if grant.expected_size > get_settings().file_library_max_file_bytes:
        raise conflict("授权期间单文件上传上限已调整，请重新申请")
    return grant


def upload_grant_size(db: Session, project_id: UUID, upload_id: UUID, token: str) -> int:
    return _upload_grant(db, project_id, upload_id, token).expected_size


def store_granted_upload(db: Session, project_id: UUID, upload_id: UUID, token: str, staged: StagedFile) -> dict:
    grant = _upload_grant(db, project_id, upload_id, token)
    if staged.size != grant.expected_size:
        raise invalid_request("上传字节数与授权不一致")
    return store_file(db, grant.actor_id, project_id, name=grant.name, request_id=grant.id, staged=staged)
