"""Web entry points for restoring work items."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import work_trash as service
from ..services.work_trash import WorkKind
from ..v2.resource_refs import parse_uuid
from .deps import current_user
from .v2_transport import V2Route

router = APIRouter(prefix="/api/v2/projects/{project_id}/trash/work", route_class=V2Route)


@router.get("")
def list_deleted(
    project_id: str, kind: WorkKind, keyword: str = "", limit: int = 20, cursor: str | None = None,
    actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.list_deleted_work(
        db, actor, parse_uuid(project_id, "project_id"), kind, keyword=keyword, limit=limit, cursor=cursor,
    )


@router.get("/{kind}/{code}")
def get_deleted(
    project_id: str, kind: WorkKind, code: str, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.deleted_work_details(db, actor, parse_uuid(project_id, "project_id"), kind, code)


@router.post("/{kind}/{code}/restore")
def restore_deleted(
    project_id: str, kind: WorkKind, code: str, actor: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.restore_work(db, actor, parse_uuid(project_id, "project_id"), kind, code)
