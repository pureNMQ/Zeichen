"""任务 API:列表/创建/详情/更新/改状态/指派/认领/解除/取消/软删/恢复。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..v2 import work_content
from ..schemas import (
    StatusBody,
    TaskAssignBody,
    TaskCreate,
    TaskUpdate,
)
from ..services import tasks as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/projects/{project_id}/tasks")
def list_tasks(
    project_id: uuid.UUID,
    requirement_id: str | None = None,
    assignee_id: uuid.UUID | None = None,
    status: list[str] | None = Query(None),
    updated_within_days: str | None = None,
    keyword: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_tasks(
        db, user, project_id, requirement_id, assignee_id, status, cursor, limit,
        updated_within_days=updated_within_days, keyword=keyword,
    )


@router.post("/projects/{project_id}/tasks", status_code=201)
def create_task(
    project_id: uuid.UUID,
    body: TaskCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return work_content.create(db, user, project_id, "tasks", body.title, body.description, body.request_id,
        requirement_id=body.requirement_id, assignee_id=body.assignee_id)


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(db, service.get_task(db, user, task_id, project_id))


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    body: TaskUpdate,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(
        db,
        service.update_task(
            db, user, task_id, body.title, body.description,
            project_id=project_id, expected_version=body.expected_version,
        ),
    )


@router.post("/tasks/{task_id}/status")
def set_status(
    task_id: str,
    body: StatusBody,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(
        db, service.set_task_status(db, user, task_id, body.status, project_id=project_id)
    )


@router.post("/tasks/{task_id}/assign")
def assign_task(
    task_id: str,
    body: TaskAssignBody,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(
        db, service.assign_task(db, user, task_id, body.assignee_id, project_id=project_id)
    )


@router.post("/tasks/{task_id}/claim")
def claim_task(
    task_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(db, service.claim_task(db, user, task_id, project_id=project_id))


@router.post("/tasks/{task_id}/unassign")
def unassign_task(
    task_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(
        db, service.unassign_task(db, user, task_id, project_id=project_id)
    )


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(
        db, service.cancel_task(db, user, task_id, project_id=project_id)
    )


@router.post("/tasks/{task_id}/delete")
def delete_task(
    task_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_task(db, user, task_id, project_id=project_id)
    return {"ok": True}


@router.post("/tasks/{task_id}/restore")
def restore_task(
    task_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._task_dict(
        db, service.restore_task(db, user, task_id, project_id=project_id)
    )
