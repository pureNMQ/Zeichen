"""Web adapter for project-scoped Markdown editor lookups."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..v2 import project_completion as service
from .deps import current_user

router = APIRouter(prefix="/api/projects", tags=["project completions"])


@router.get("/{project_id}/completions")
def completions(
    project_id: uuid.UUID,
    mode: Literal["people", "reference"],
    q: str = Query(default="", max_length=200),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": service.completion_candidates(db, user, project_id, mode, q)}


@router.get("/{project_id}/people/{person_id}")
def project_person(
    project_id: uuid.UUID,
    person_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.get_person(db, user, project_id, person_id)
