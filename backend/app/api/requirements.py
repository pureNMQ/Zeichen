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
from ..services.permissions import require_project_role
from .deps import current_user

router = APIRouter(prefix="/api", tags=["requirements"])


@router.get("/projects/{project_id}/requirements")
def list_requirements(
    project_id: uuid.UUID,
    status: list[str] | None = Query(None),
    updated_within_days: str | None = None,
    keyword: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_requirements(
        db, user, project_id, status, cursor, limit,
        updated_within_days=updated_within_days, keyword=keyword,
    )


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


@router.get("/projects/{project_id}/requirements/{requirement_id}")
def get_requirement_in_project(
    project_id: uuid.UUID,
    requirement_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.get_requirement_in_project(db, project_id, requirement_id)
    return service._requirement_dict(db, requirement)


@router.post("/projects/{project_id}/requirements/{requirement_id}/status")
def set_status_in_project(
    project_id: uuid.UUID,
    requirement_id: str,
    body: StatusBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """项目内改状态(ADR 0002):跨项目同码时优先使用,避免消歧歧义。"""
    requirement = service.get_requirement_in_project(db, project_id, requirement_id)
    require_project_role(db, user.id, project_id, min_level="editor")
    from ..services.workflow import assert_status_valid

    assert_status_valid(requirement.status, body.status, "需求")
    from ..services.labels import STATUS_CN

    old = requirement.status
    requirement.status = body.status
    from ..services.polymorphic import record_activity

    record_activity(
        db,
        project_id,
        user.id,
        "requirement",
        requirement.code,
        "status",
        f"{STATUS_CN[old]} → {STATUS_CN[body.status]}",
    )
    db.commit()
    return service._requirement_dict(db, requirement)


@router.get("/requirements/{requirement_id}")
def get_requirement(
    requirement_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._requirement_dict(
        db, service.get_requirement(db, user, requirement_id, project_id)
    )


@router.patch("/requirements/{requirement_id}")
def update_requirement(
    requirement_id: str,
    body: RequirementUpdate,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.update_requirement(
        db, user, requirement_id, body.title, body.description, project_id=project_id
    )
    return service._requirement_dict(db, requirement)


@router.post("/requirements/{requirement_id}/status")
def set_status(
    requirement_id: str,
    body: StatusBody,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.set_requirement_status(
        db, user, requirement_id, body.status, project_id=project_id
    )
    return service._requirement_dict(db, requirement)


@router.post("/requirements/{requirement_id}/cancel")
def cancel_requirement(
    requirement_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.cancel_requirement(db, user, requirement_id, project_id=project_id)
    return service._requirement_dict(db, requirement)


@router.post("/requirements/{requirement_id}/delete")
def delete_requirement(
    requirement_id: str,
    body: RequirementDeleteBody | None = None,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_requirement(
        db, user, requirement_id, body.confirm_task_count if body else None,
        project_id=project_id,
    )
    return {"ok": True}


@router.post("/requirements/{requirement_id}/restore")
def restore_requirement(
    requirement_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._requirement_dict(
        db, service.restore_requirement(db, user, requirement_id, project_id=project_id)
    )
