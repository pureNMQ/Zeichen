"""需求 API:列表/创建/详情/更新/改状态/取消/软删/恢复。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import invalid_request
from ..services.requirement_board import set_blockers
from ..models import User
from ..v2 import work_content
from ..schemas import (
    RequirementCreate,
    RequirementDeleteBody,
    RequirementRejectBody,
    RequirementUpdate,
    StatusBody,
)
from ..services import requirements as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user
from .v2_transport import commit_command

router = APIRouter(prefix="/api", tags=["requirements"])


@router.get("/projects/{project_id}/requirements")
def list_requirements(
    project_id: uuid.UUID,
    status: list[str] | None = Query(None),
    updated_within_days: str | None = None,
    keyword: str | None = None,
    participated_by_me: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_requirements(
        db, user, project_id, status, cursor, limit,
        updated_within_days=updated_within_days, keyword=keyword, participated_by_me=participated_by_me,
    )


@router.post("/projects/{project_id}/requirements", status_code=201)
def create_requirement(
    project_id: uuid.UUID,
    body: RequirementCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return work_content.create(db, user, project_id, "requirements", body.title, body.description, body.request_id)


@router.get("/projects/{project_id}/requirements/{requirement_id}")
def get_requirement_in_project(
    project_id: uuid.UUID,
    requirement_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    requirement = service.get_requirement(db, user, requirement_id, project_id=project_id)
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
    requirement = service.set_requirement_status(db, user, requirement_id, body.status, project_id=project_id)
    return service._requirement_dict(db, requirement)


@router.post("/projects/{project_id}/requirements/{requirement_id}/reject")
def reject_requirement(
    project_id: uuid.UUID, requirement_id: str, body: RequirementRejectBody,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return commit_command(db, lambda: service.reject_requirement(
        db, user, project_id, requirement_id, body.reason, body.request_id,
    ))


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
    if body.model_fields_set & {"blocked_by", "expected_blocked_by"}:
        if body.model_fields_set - {"blocked_by", "expected_blocked_by"} or body.blocked_by is None:
            raise invalid_request("请单独提交前置需求编号列表")
        return service._requirement_dict(db, set_blockers(
            db, user, requirement_id, project_id, body.blocked_by, body.expected_blocked_by))
    requirement = service.update_requirement(
        db, user, requirement_id, body.title, body.description, project_id=project_id, expected_version=body.expected_version
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
