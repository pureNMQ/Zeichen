"""附件 API:上传(multipart)/下载/列表/删除/恢复(挂任意实体)。

Web 端经 multipart 上传,与 MCP 的 bytes 参数共用同一 service 层。
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import attachments as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api", tags=["attachments"])


@router.post("/targets/{target_type}/{target_id}/attachments", status_code=201)
def upload_attachment(
    target_type: str,
    target_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project_id = uuid.UUID(str(_target_project(db, target_type, target_id)))
    data = file.file.read()
    try:
        a = service.upload(
            db, user, project_id, target_type, target_id, file.filename or "file", data
        )
    finally:
        file.file.close()
    return service._attachment_dict(db, a)


def _target_project(db, target_type: str, target_id: uuid.UUID):
    from ..services.polymorphic import resolve_target

    return resolve_target(db, target_type, target_id).id


@router.get("/targets/{target_type}/{target_id}/attachments")
def list_attachments(
    target_type: str,
    target_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_attachments(db, user, target_type, target_id, cursor, limit)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    from urllib.parse import quote

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
