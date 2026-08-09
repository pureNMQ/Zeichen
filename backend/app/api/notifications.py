"""通知 API:列表 / 未读数 / 标记已读 / 全部已读。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import notifications as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_notifications(db, user, cursor, limit, unread_only)


@router.get("/unread-count")
def get_unread_count(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"count": service.unread_count(db, user)}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.mark_read(db, user, notification_id)
    return {"ok": True}


@router.post("/read-all")
def mark_all_read(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.mark_all_read(db, user)
    return {"ok": True}
