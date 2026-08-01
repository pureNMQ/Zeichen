"""两级角色判权(规格书 §5.1)。

- 工作区:admin / member(workspace_member,team 单例)
- 项目:owner / editor / viewer(project_member)
- admin 自动拥有所有项目 owner 级访问;判权只看角色,不看主体类型
"""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, ProjectMember, Team, WorkspaceMember

ROLE_LEVEL = {"viewer": 1, "editor": 2, "owner": 3}


def get_team(db: Session) -> Team:
    team = db.scalar(select(Team).order_by(Team.created_at).limit(1))
    if team is None:
        raise HTTPException(status_code=409, detail="工作区尚未初始化,请先完成首用户引导")
    return team


def get_workspace_member(db: Session, user_id) -> WorkspaceMember | None:
    team = get_team(db)
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.team_id == team.id, WorkspaceMember.user_id == user_id
        )
    )


def is_admin(db: Session, user_id) -> bool:
    wm = get_workspace_member(db, user_id)
    return wm is not None and wm.role == "admin"


def require_workspace_admin(db: Session, user_id) -> None:
    if not is_admin(db, user_id):
        raise HTTPException(status_code=403, detail="仅工作区管理员可执行")


def get_project_role(db: Session, user_id, project_id) -> str | None:
    """admin 自动全项目 owner;否则查 project_member。"""
    if is_admin(db, user_id):
        return "owner"
    pm = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )
    return pm.role if pm else None


def get_accessible_project(
    db: Session, user_id, project_id, min_level: str = "viewer"
) -> Project:
    """项目不存在或用户非成员 → 404(不泄露存在性);成员但权限不足 → 403。"""
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无访问权限")
    role = get_project_role(db, user_id, project_id)
    if role is None:
        raise HTTPException(status_code=404, detail="项目不存在或无访问权限")
    if ROLE_LEVEL[role] < ROLE_LEVEL[min_level]:
        raise HTTPException(status_code=403, detail="项目权限不足")
    return project
