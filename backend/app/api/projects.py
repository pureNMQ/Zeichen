"""项目 API:列表(admin 全量/member 已加入)、建项目(admin)、项目成员管理(owner/admin)。"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, User
from ..schemas import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberUpdate,
    ProjectOwnerTransfer,
    ProjectDelete,
    ProjectUpdate,
)
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


@router.patch("/{project_id}")
def update_project(
    project_id: uuid.UUID,
    body: ProjectUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = projects_service.update_project(db, user, project_id, body.name)
    return {"id": str(project.id), "name": project.name}


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
            "is_current_user": u.id == user.id,
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


@router.patch("/{project_id}/members/{user_id}")
def update_project_member_role(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ProjectMemberUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    projects_service.update_project_member_role(db, user, project_id, user_id, body.role)
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


@router.post("/{project_id}/owner-transfer")
def transfer_project_owner(
    project_id: uuid.UUID,
    body: ProjectOwnerTransfer,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    projects_service.transfer_project_owner(
        db, user, project_id, body.user_id, body.password
    )
    return {"ok": True}


@router.delete("/{project_id}")
def delete_project(
    project_id: uuid.UUID,
    body: ProjectDelete,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not body.confirm_memory_cleanup:
        from ..errors import invalid_request
        raise invalid_request("必须确认永久清理项目记忆与会话缓存")
    projects_service.soft_delete_project(db, user, project_id)
    return {"ok": True}


@router.get("/{project_id}/member_candidates")
def list_member_candidates(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        {"id": str(u.id), "username": u.username, "is_agent": u.is_agent}
        for u in projects_service.list_member_candidates(db, user, project_id)
    ]
