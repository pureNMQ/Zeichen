"""Human Web API for project-scoped shared memory."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import MemoryImprove, MemoryRecall, MemoryRemember
from ..services import memory as memory_service
from ..services import memory_improve_jobs as improve_jobs
from .deps import current_user

router = APIRouter(prefix="/api/projects/{project_id}/memory", tags=["memory"])


@router.get("")
def list_memory(project_id: uuid.UUID, source_id: uuid.UUID | None = Query(default=None), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return memory_service.list_memory(db, user, project_id, source_id)


@router.post("/recall")
def recall(project_id: uuid.UUID, body: MemoryRecall, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"result": memory_service.recall(db, user, project_id, body.query, body.session_id)}


@router.post("/remember")
def remember(project_id: uuid.UUID, body: MemoryRemember, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"result": memory_service.remember(db, user, project_id, body.session_id, body.content, body.anchor)}


@router.post("/improve")
def improve(project_id: uuid.UUID, body: MemoryImprove, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"job": improve_jobs.submit(db, user, project_id, body.agent_id, body.session_id)}


@router.get("/improve-jobs/{job_id}")
def get_improve_job(job_id: uuid.UUID, project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"job": improve_jobs.get(db, user, project_id, job_id)}


@router.get("/sessions")
def list_sessions(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"items": memory_service.list_sessions(db, user, project_id)}


@router.get("/sessions/{session_id}")
def get_session_detail(session_id: str, project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return memory_service.get_session_detail(db, user, project_id, session_id)


@router.delete("/{data_id}")
def forget(data_id: str, project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"result": memory_service.forget(db, user, project_id, data_id)}
