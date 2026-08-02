"""需求 API:列表/创建/详情/更新/改状态/取消/软删/恢复。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import (
    RequirementCreate,
    RequirementDeleteBody,
    RequirementUpdate,
    StatusBody,
)
from ..services import requirements as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api", tags=["requirements"])


@router.get("/projects/{project_id}/requirements")
def list_requirements(
    project_id: uuid.UUID,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_requirements(db, user, project_id, status, cursor, limit)


@router.post("/projects/{project_id}/requirements", status_code=201)
def create_requirement(
    project_id: uuid.UUID,
    body: RequirementCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.create_requirement(
        db, user, project_id, body.title, body.description
    )
    return service._requirement_dict(db, requirement)


@router.get("/requirements/{requirement_id}")
def get_requirement(
    requirement_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._requirement_dict(db, service.get_requirement(db, user, requirement_id))


@router.patch("/requirements/{requirement_id}")
def update_requirement(
    requirement_id: uuid.UUID,
    body: RequirementUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.update_requirement(
        db, user, requirement_id, body.title, body.description
    )
    return service._requirement_dict(db, requirement)


@router.post("/requirements/{requirement_id}/status")
def set_status(
    requirement_id: uuid.UUID,
    body: StatusBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.set_requirement_status(db, user, requirement_id, body.status)
    return service._requirement_dict(db, requirement)


@router.post("/requirements/{requirement_id}/cancel")
def cancel_requirement(
    requirement_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.cancel_requirement(db, user, requirement_id)
    return service._requirement_dict(db, requirement)


@router.post("/requirements/{requirement_id}/delete")
def delete_requirement(
    requirement_id: uuid.UUID,
    body: RequirementDeleteBody | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_requirement(
        db, user, requirement_id, body.confirm_task_count if body else None
    )
    return {"ok": True}


@router.post("/requirements/{requirement_id}/restore")
def restore_requirement(
    requirement_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._requirement_dict(db, service.restore_requirement(db, user, requirement_id))
