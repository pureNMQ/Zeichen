"""Web-only workspace administration endpoints for Cognee."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import CogneeConfigurationUpdate, CogneeRestartRequest
from ..services import cognee_configuration as service
from ..services import cognee_restart_jobs
from .deps import current_admin

router = APIRouter(prefix="/api/cognee/configuration", tags=["cognee"])


@router.get("")
def get_configuration(admin: User = Depends(current_admin), db: Session = Depends(get_db)) -> dict:
    return service.payload(service.get_or_create(db))


@router.put("")
def update_configuration(
    body: CogneeConfigurationUpdate,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    values = body.model_dump(exclude_unset=True)
    # All non-secret fields are required by the schema; a missing secret means
    # retain it, while an explicit empty string clears it.
    return service.payload(service.update(db, values))


@router.get("/status")
def get_runtime_status(admin: User = Depends(current_admin), db: Session = Depends(get_db)) -> dict:
    return service.runtime_status(db)


@router.post("/restarts", status_code=202)
def restart_cognee(
    body: CogneeRestartRequest,
    admin: User = Depends(current_admin),
    db: Session = Depends(get_db),
) -> dict:
    return {"job": cognee_restart_jobs.submit(db, admin, body.confirmed)}


@router.get("/restarts/{job_id}")
def get_restart(job_id: uuid.UUID, admin: User = Depends(current_admin), db: Session = Depends(get_db)) -> dict:
    return {"job": cognee_restart_jobs.get(db, job_id)}
