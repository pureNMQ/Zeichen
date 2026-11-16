"""Explicit v2 business notifications."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..v2 import notifications as service
from ..v2.resource_refs import parse_uuid
from .deps import current_user
from .v2_transport import V2Route, commit_command


router = APIRouter(prefix="/api/v2/notifications", tags=["notifications v2"], route_class=V2Route)


@router.get("")
def list_items(
    cursor: str | None = None, limit: int = 20, unread_only: bool = False,
    actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.list_notifications(db, actor, cursor=cursor, limit=limit, unread_only=unread_only)


@router.get("/unread-count")
def count_unread(actor: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"count": service.unread_count(db, actor)}


@router.get("/{notification_id}")
def get_item(
    notification_id: str, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.get_notification(db, actor, parse_uuid(notification_id, "notification_id"))


@router.post("/{notification_id}/read")
@router.post("/{notification_id}/open")
def acknowledge(
    notification_id: str, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return commit_command(db, lambda: service.mark_read(
        db, actor, parse_uuid(notification_id, "notification_id"),
    ))
