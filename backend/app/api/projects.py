"""项目 API:列表(admin 全量/member 已加入)、建项目(admin)、项目成员管理(owner/admin)。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, User
from ..schemas import ProjectCreate, ProjectMemberAdd
from ..services import projects as projects_service
from .deps import current_user

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "created_at": p.created_at.isoformat(),
            "my_role": role,
        }
        for p, role in projects_service.list_projects(db, user)
    ]


@router.post("", status_code=201)
def create_project(
    body: ProjectCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    project = projects_service.create_project(
        db, user, body.name.strip(), [m.model_dump() for m in body.members]
    )
    return {"id": str(project.id), "name": project.name, "my_role": "owner"}

@router.get("/{project_id}")
def get_project(
    project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    project, role = projects_service.get_project(db, user, project_id)
    return {
        "id": str(project.id),
        "name": project.name,
        "created_at": project.created_at.isoformat(),
        "my_role": role,
    }


@router.get("/{project_id}/members")
def list_project_members(
    project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        {
            "id": str(u.id),
            "username": u.username,
            "is_agent": u.is_agent,
            "role": role,
        }
        for u, role in projects_service.list_project_members(db, user, project_id)
    ]


@router.post("/{project_id}/members", status_code=201)
def add_project_member(
    project_id: uuid.UUID,
    body: ProjectMemberAdd,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    projects_service.add_project_member(db, user, project_id, body.user_id, body.role)
    return {"ok": True}


@router.delete("/{project_id}/members/{user_id}")
def remove_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    projects_service.remove_project_member(db, user, project_id, user_id)
    return {"ok": True}
