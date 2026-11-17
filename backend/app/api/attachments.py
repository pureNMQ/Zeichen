"""附件 API:上传(multipart)/下载/列表/删除/恢复(挂任意实体)。

Web 端经 multipart 上传,与 MCP 的 bytes 参数共用同一 service 层。
"""

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Attachment, User
from ..services import attachments as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..v2.file_models import ProjectFile
from .deps import current_user
from .files_v2 import download_file

router = APIRouter(prefix="/api", tags=["attachments"])


@router.post("/targets/{target_type}/{target_id}/attachments", status_code=201)
def upload_attachment(
    target_type: str,
    target_id: str,
    file: UploadFile = File(...),
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if project_id is None:
        project_id = _target_project(db, target_type, target_id, user)
    data = file.file.read()
    try:
        a = service.upload(
            db, user, project_id, target_type, target_id, file.filename or "file", data
        )
    finally:
        file.file.close()
    return service._attachment_dict(db, a)


def _target_project(db, target_type: str, target_id: str, user):
    from ..services.polymorphic import resolve_target

    return resolve_target(db, target_type, target_id, user=user).id


@router.get("/targets/{target_type}/{target_id}/attachments")
def list_attachments(
    target_type: str,
    target_id: str,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_attachments(
        db, user, target_type, target_id, cursor, limit, project_id=project_id
    )


@router.head("/attachments/{attachment_id}/download", include_in_schema=False)
@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    from urllib.parse import quote

    legacy = db.get(Attachment, attachment_id)
    if legacy is not None and legacy.project_id is not None:
        if db.get(ProjectFile, (legacy.project_id, attachment_id)) is not None:
            return download_file(legacy.project_id, attachment_id, user, db)

    file_name, data, _ = service.download(db, user, attachment_id)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename*=UTF-8\'\'{quote(file_name)}'
        },
    )


@router.delete("/attachments/{attachment_id}")
def delete_attachment(
    attachment_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.soft_delete(db, user, attachment_id)
    return {"ok": True}


@router.post("/attachments/{attachment_id}/restore")
def restore_attachment(
    attachment_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    a = service.restore(db, user, attachment_id)
    return service._attachment_dict(db, a)
