"""多态 API:comment / activity / reference(挂任意实体)。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import CommentCreate
from ..v2 import backlinks
from ..services import notifications as notification_service
from ..services import polymorphic as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api", tags=["polymorphic"])


@router.get("/targets/{target_type}/{target_id}/comments")
def list_comments(
    target_type: str,
    target_id: str,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_comments(
        db, user, target_type, target_id, cursor, limit, project_id=project_id
    )


@router.post("/targets/{target_type}/{target_id}/comments", status_code=201)
def create_comment(
    target_type: str,
    target_id: str,
    body: CommentCreate,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    comment = service.create_comment(
        db, user, target_type, target_id, body.body, project_id=project_id
    )
    return {"id": str(comment.id), "target_type": comment.target_type, "target_id": comment.target_id, "body": comment.body}


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
    target_id: str,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_activity(
        db, user, target_type, target_id, cursor, limit, project_id=project_id
    )


@router.get("/projects/{project_id}/markdown/backlinks")
def markdown_backlinks(project_id: uuid.UUID, target_kind: backlinks.BodyKind, target_id: str,
                       cursor: str | None = None, limit: int = Query(50, ge=1, le=100),
                       user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return backlinks.list_backlinks(db, user, project_id, target_kind, target_id, cursor, limit)


@router.get("/targets/{target_type}/{target_id}/watch")
def get_watch_state(
    target_type: str,
    target_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "watching": notification_service.is_watching(
            db, user, target_type, target_id, project_id=project_id
        )
    }


@router.post("/targets/{target_type}/{target_id}/watch", status_code=201)
def watch_target(
    target_type: str,
    target_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    notification_service.watch_entity(
        db, user, target_type, target_id, project_id=project_id
    )
    return {"watching": True}


@router.delete("/targets/{target_type}/{target_id}/watch")
def unwatch_target(
    target_type: str,
    target_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    notification_service.unwatch_entity(
        db, user, target_type, target_id, project_id=project_id
    )
    return {"watching": False}
