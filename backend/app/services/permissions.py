"""两级角色判权(规格书 §5.1)。

- 工作区:admin / member(workspace_member,team 单例)
- 项目:owner / editor / viewer(project_member)
- admin 自动拥有所有项目 owner 级访问;判权只看角色,不看主体类型
- ADR 0004 附属化:is_agent 主体判权一律动态解析其主人当前角色
  (主人 admin→全项目 owner 级;主人被移除/软删后 agent 即无任何权限)
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, not_found, permission_denied
from ..models import Project, ProjectMember, Team, User, WorkspaceMember

ROLE_LEVEL = {"viewer": 1, "editor": 2, "owner": 3}


def get_team(db: Session) -> Team:
    team = db.scalar(select(Team).order_by(Team.created_at).limit(1))
    if team is None:
        raise conflict("工作区尚未初始化,请先完成首用户引导")
    return team


def effective_user_id(db: Session, user_id) -> uuid.UUID | None:
    """判权主体解析:附属 Agent → 主人 id;主人失效(移除/软删)返回 None。

    人类成员与无主 agent(理论不存在,防御)返回原 id/None。
    """
    user = db.get(User, user_id)
    if user is not None and user.is_agent and user.owner_id is not None:
        owner = db.get(User, user.owner_id)
        if owner is None or owner.deleted_at is not None:
            return None
        return owner.id
    if user is not None and user.is_agent:
        return None
    return user_id


def get_workspace_member(db: Session, user_id) -> WorkspaceMember | None:
    eid = effective_user_id(db, user_id)
    if eid is None:
        return None
    team = get_team(db)
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.team_id == team.id, WorkspaceMember.user_id == eid
        )
    )


def is_admin(db: Session, user_id) -> bool:
    eid = effective_user_id(db, user_id)
    if eid is None:
        return False
    wm = get_workspace_member(db, eid)
    return wm is not None and wm.role == "admin"


def require_workspace_admin(db: Session, user_id) -> None:
    if not is_admin(db, user_id):
        raise permission_denied("仅工作区管理员可执行")


def get_project_role(db: Session, user_id, project_id) -> str | None:
    """admin 自动全项目 owner;否则查 project_member;附属 agent 按主人判定。"""
    eid = effective_user_id(db, user_id)
    if eid is None:
        return None
    if is_admin(db, eid):
        return "owner"
    pm = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == eid
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
        raise not_found("项目不存在或无访问权限")
    role = get_project_role(db, user_id, project_id)
    if role is None:
        raise not_found("项目不存在或无访问权限")
    if ROLE_LEVEL[role] < ROLE_LEVEL[min_level]:
        raise permission_denied("项目权限不足")
    return project


def require_project_role(db: Session, user_id, project_id, min_level: str = "editor") -> str:
    """项目访问 + 最低角色校验,返回实际角色(editor/owner)。"""
    get_accessible_project(db, user_id, project_id, min_level=min_level)
    return get_project_role(db, user_id, project_id) or "viewer"
