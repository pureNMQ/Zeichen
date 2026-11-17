"""Cookie-authenticated library and short-lived no-cookie read transport."""

import logging
from collections.abc import Callable
from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session
from starlette.responses import FileResponse

from ..config import get_settings
from ..db import get_db
from ..errors import conflict, invalid_request, not_found
from ..models import User
from ..v2 import file_usage, files
from ..v2.file_models import ProjectFile
from ..v2.file_storage import StagedFile, file_path, stage_file, supports_preview
from .deps import current_user

router = APIRouter(prefix="/api/v2", tags=["files v2"])
_LIBRARY = "/projects/{project_id}/files"
_TRANSFER = "/file-transfers/{project_id}/{file_id}"


class _TransferLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str) and args[2].startswith(files.TRANSFER_PATH):
            record.args = (*args[:2], args[2].partition("?")[0], *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_TransferLogFilter())


class RenameFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str


@router.get(_LIBRARY)
def list_library(
    project_id: UUID,
    actor: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
    query: Annotated[str, Query(max_length=256)] = "",
    media_type: Annotated[str | None, Query(max_length=80)] = None,
    uploader_id: UUID | None = None,
    images_only: bool = False,
    state: files.FileState = files.FileState.ACTIVE,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    return files.list_files(db, actor.id, project_id, query=query, media_type=media_type, uploader_id=uploader_id,
                            images_only=images_only, state=state, cursor=cursor, limit=limit)


@router.get(_LIBRARY + "/limits")
def file_limits(project_id: UUID, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    files.require_file_access(db, actor.id, project_id)
    settings = get_settings()
    return {"max_file_bytes": settings.file_library_max_file_bytes,
            "project_quota_bytes": settings.file_library_project_quota_bytes}


def _save_upload(db: Session, save: Callable[[StagedFile], dict], staged: StagedFile) -> dict:
    try:
        saved = save(staged)
    except Exception:
        db.rollback()
        staged.discard_uncommitted_bytes()
        raise
    # If commit outcome is indeterminate, leave bytes in place. A reconciliation
    # pass can report unreferenced blobs without removing an accepted upload.
    db.commit()
    return saved


async def _receive_upload(request: Request, db: Session, byte_limit: int, save: Callable[[StagedFile], dict]) -> dict:
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdigit() or len(length) > 20:
            raise invalid_request("Content-Length 无效")
        if int(length) > byte_limit:
            raise conflict("文件超过本次上传字节上限")
    # Release the initial authorization transaction while receiving the body;
    # the save command checks the current authorizer again before writing.
    await run_in_threadpool(db.rollback)
    with stage_file(byte_limit=byte_limit) as staged:
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(staged.write, chunk)
        return await run_in_threadpool(_save_upload, db, save, staged)


@router.post(_LIBRARY, status_code=201)
async def upload_file(
    project_id: UUID, request: Request,
    actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Query(min_length=1, max_length=255)], request_id: UUID,
) -> dict:
    actor_id = actor.id
    await run_in_threadpool(files.require_file_access, db, actor_id, project_id, edit=True)
    def save(staged: StagedFile) -> dict:
        return files.store_file(db, actor_id, project_id, name=name, request_id=request_id, staged=staged)

    return await _receive_upload(request, db, get_settings().file_library_max_file_bytes, save)


@router.get(_LIBRARY + "/associations")
def associated_files(
    project_id: UUID, target_kind: file_usage.TargetKind, target_id: str,
    actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
    cursor: Annotated[str | None, Query(max_length=256)] = None, limit: int = 20,
) -> dict:
    return file_usage.list_associated_files(
        db, actor.id, project_id, kind=target_kind, target_id=target_id, cursor=cursor, limit=limit,
    )


@router.get(_LIBRARY + "/{file_id}")
def read_metadata(project_id: UUID, file_id: UUID, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    return files.file_summary(files.get_file(db, actor.id, project_id, file_id), detail=True)


@router.get(_LIBRARY + "/{file_id}/trash")
def read_deleted_metadata(
    project_id: UUID, file_id: UUID, actor: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return files.file_summary(files.get_deleted_file(db, actor.id, project_id, file_id), detail=True)


@router.get(_LIBRARY + "/{file_id}/usage")
def read_usage(
    project_id: UUID, file_id: UUID, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
    include_history: bool = False, cursor: str | None = None, limit: int = 20,
) -> file_usage.UsagePage:
    return file_usage.list_usage(db, actor.id, project_id, file_id, include_history=include_history, cursor=cursor, limit=limit)


@router.put(_LIBRARY + "/{file_id}/usage")
def link_file(
    project_id: UUID, file_id: UUID, target_kind: file_usage.TargetKind, target_id: str,
    actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
) -> file_usage.AssociationReceipt:
    result = file_usage.set_association(db, actor.id, project_id, file_id, kind=target_kind, target_id=target_id, linked=True)
    db.commit()
    return result


@router.delete(_LIBRARY + "/{file_id}/usage")
def unlink_file(
    project_id: UUID, file_id: UUID, target_kind: file_usage.TargetKind, target_id: str,
    actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)],
) -> file_usage.AssociationReceipt:
    result = file_usage.set_association(db, actor.id, project_id, file_id, kind=target_kind, target_id=target_id, linked=False)
    db.commit()
    return result


@router.patch(_LIBRARY + "/{file_id}")
def rename_file(project_id: UUID, file_id: UUID, patch: RenameFile,
                actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    row = files.rename_file(db, actor.id, project_id, file_id, patch.name)
    db.commit()
    return files.file_summary(row)


@router.delete(_LIBRARY + "/{file_id}")
def remove_file(project_id: UUID, file_id: UUID, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    files.delete_file(db, actor.id, project_id, file_id)
    db.commit()
    return {"id": str(file_id), "project_id": str(project_id), "deleted": True}


@router.post(_LIBRARY + "/{file_id}/restore")
def restore_file(project_id: UUID, file_id: UUID, actor: Annotated[User, Depends(current_user)], db: Annotated[Session, Depends(get_db)]) -> dict:
    row = files.restore_file(db, actor.id, project_id, file_id)
    db.commit()
    return files.file_summary(row)


def _send_file(row: ProjectFile, *, inline: bool) -> FileResponse:
    path = file_path(row.project_id, row.id)
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise not_found("文件字节不存在") from None
    if stat.st_size != row.size:
        raise not_found("文件字节不完整")
    inline = inline and supports_preview(row.media_type)
    return FileResponse(
        path, stat_result=stat, filename=row.name,
        media_type=row.media_type if inline else "application/octet-stream",
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
                 "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"},
    )


@router.head(_LIBRARY + "/{file_id}/content", include_in_schema=False)
@router.get(_LIBRARY + "/{file_id}/content")
def download_file(project_id: UUID, file_id: UUID, actor: Annotated[User, Depends(current_user)],
                  db: Annotated[Session, Depends(get_db)], inline: bool = False) -> FileResponse:
    return _send_file(files.get_file(db, actor.id, project_id, file_id), inline=inline)


@router.head(_TRANSFER, include_in_schema=False)
@router.get(_TRANSFER)
def download_by_grant(project_id: UUID, file_id: UUID, grant: str, db: Annotated[Session, Depends(get_db)]) -> FileResponse:
    row, inline = files.redeem_read_grant(db, project_id, file_id, grant)
    return _send_file(row, inline=inline)


@router.put("/file-transfers/{project_id}/{upload_id}", status_code=201)
async def upload_by_grant(project_id: UUID, upload_id: UUID, grant: str, request: Request,
                          db: Annotated[Session, Depends(get_db)]) -> dict:
    size = await run_in_threadpool(files.upload_grant_size, db, project_id, upload_id, grant)
    return await _receive_upload(request, db, size, partial(files.store_granted_upload, db, project_id, upload_id, grant))
