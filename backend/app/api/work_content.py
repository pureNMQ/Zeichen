"""Requirement/task document history, mounted after the Wiki's version routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..v2 import work_content as service
from .deps import current_user

router = APIRouter(prefix="/api/projects/{project_id}/{kind}/{code}/versions", tags=["work content"])


class RestoreBody(BaseModel):
    expected_version: int = Field(ge=1)


@router.get("")
def versions(project_id: UUID, kind: service.WorkKind, code: str, before: int | None = None,
             limit: int = Query(default=50, ge=1, le=100), user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    return service.versions(db, user, project_id, kind, code, before, limit)


@router.get("/{number}")
def version(project_id: UUID, kind: service.WorkKind, code: str, number: int,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    return service.version(db, user, project_id, kind, code, number)


@router.post("/{number}/restore")
def restore(project_id: UUID, kind: service.WorkKind, code: str, number: int, body: RestoreBody,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    return service.restore(db, user, project_id, kind, code, number, body.expected_version)
