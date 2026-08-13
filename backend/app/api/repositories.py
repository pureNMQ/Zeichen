"""HTTP API for project code repository registration."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import RepositoryCreate, RepositoryUpdate
from ..services import repositories as service
from .deps import current_user

router = APIRouter(prefix="/api", tags=["repositories"])


@router.get("/projects/{project_id}/repositories")
def list_repositories(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_repositories(db, user, project_id)}


@router.get("/projects/{project_id}/repositories/deleted")
def list_deleted_repositories(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_repositories(db, user, project_id, deleted=True)}


@router.post("/projects/{project_id}/repositories", status_code=201)
def create_repository(project_id: uuid.UUID, body: RepositoryCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._repository_dict(service.create_repository(db, user, project_id, body.model_dump()))


@router.get("/repositories/{repository_id}")
def get_repository(repository_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.get_repository(db, user, repository_id)


@router.patch("/repositories/{repository_id}")
def update_repository(repository_id: uuid.UUID, body: RepositoryUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._repository_dict(service.update_repository(db, user, repository_id, body.model_dump(exclude_unset=True)))


@router.post("/repositories/{repository_id}/delete")
def delete_repository(repository_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    service.delete_repository(db, user, repository_id)
    return {"ok": True}


@router.post("/repositories/{repository_id}/restore")
def restore_repository(repository_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._repository_dict(service.restore_repository(db, user, repository_id))
