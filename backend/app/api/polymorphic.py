"""多态 API:comment / activity / reference(挂任意实体)。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import CommentCreate, ReferenceCreate
from ..services import polymorphic as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api", tags=["polymorphic"])


@router.get("/targets/{target_type}/{target_id}/comments")
def list_comments(
    target_type: str,
    target_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_comments(db, user, target_type, target_id, cursor, limit)


@router.post("/targets/{target_type}/{target_id}/comments", status_code=201)
def create_comment(
    target_type: str,
    target_id: uuid.UUID,
    body: CommentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    comment = service.create_comment(db, user, target_type, target_id, body.body)
    return {"id": str(comment.id), "target_type": comment.target_type, "target_id": str(comment.target_id), "body": comment.body}


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_comment(db, user, comment_id)
    return {"ok": True}


@router.get("/targets/{target_type}/{target_id}/activity")
def list_activity(
    target_type: str,
    target_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_activity(db, user, target_type, target_id, cursor, limit)


@router.get("/targets/{target_type}/{target_id}/references")
def list_references(
    target_type: str,
    target_id: uuid.UUID,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_references(db, user, target_type, target_id, cursor, limit)


@router.post("/targets/{target_type}/{target_id}/references", status_code=201)
def create_reference(
    target_type: str,
    target_id: uuid.UUID,
    body: ReferenceCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    ref = service.create_reference(
        db, user, body.from_type, body.from_id, body.to_type, body.to_id, body.type
    )
    return {
        "id": str(ref.id),
        "from_type": ref.from_type,
        "from_id": str(ref.from_id),
        "to_type": ref.to_type,
        "to_id": str(ref.to_id),
        "type": ref.type,
    }


@router.delete("/references/{ref_id}")
def delete_reference(
    ref_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_reference(db, user, ref_id)
    return {"ok": True}
