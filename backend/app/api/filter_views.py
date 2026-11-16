"""筛选视图 API:个人筛选视图持久化(列表/创建/详情/更新/删除)。

- 列表/创建挂在项目路径下(entity_type 必填,校验在 service → 400)
- 详情/更新/删除按 (id, user_id) 过滤,非本人一律 404
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import FilterViewCreate, FilterViewUpdate
from ..services import filter_views as service
from .deps import current_user

router = APIRouter(prefix="/api", tags=["filter-views"])


@router.get("/projects/{project_id}/filter-views")
def list_filter_views(
    project_id: uuid.UUID,
    entity_type: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_filter_views(db, user, project_id, entity_type)


@router.post("/projects/{project_id}/filter-views", status_code=201)
def create_filter_view(
    project_id: uuid.UUID,
    body: FilterViewCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    view = service.create_filter_view(
        db, user, project_id, body.entity_type, body.name, body.criteria
    )
    return service._view_dict(view)


@router.get("/filter-views/{view_id}")
def get_filter_view(
    view_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._view_dict(service.get_filter_view(db, user, view_id))


@router.patch("/filter-views/{view_id}")
def update_filter_view(
    view_id: uuid.UUID,
    body: FilterViewUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    fields = body.model_fields_set
    view = service.update_filter_view(
        db,
        user,
        view_id,
        name=body.name if "name" in fields else None,
        criteria=body.criteria if "criteria" in fields else None,
        name_set="name" in fields,
        criteria_set="criteria" in fields,
    )
    return service._view_dict(view)


@router.delete("/filter-views/{view_id}")
def delete_filter_view(
    view_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    service.delete_filter_view(db, user, view_id)
    return {"ok": True}
