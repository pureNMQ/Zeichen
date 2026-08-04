"""项目服务:建项目(admin)、列表(admin 全量/member 已加入)、项目成员管理(owner/admin)。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Project, ProjectMember, User, WorkspaceMember
from .permissions import get_accessible_project, get_project_role, get_team, is_admin, require_workspace_admin
from ..security import verify_password

PROJECT_ROLES = ("owner", "editor", "viewer")


def list_projects(db: Session, user: User) -> list[tuple[Project, str]]:
    team = get_team(db)
    if is_admin(db, user.id):
        projects = db.scalars(
            select(Project)
            .where(Project.team_id == team.id, Project.deleted_at.is_(None))
            .order_by(Project.created_at)
        ).all()
        return [(p, "owner") for p in projects]
    rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectMember.user_id == user.id,
            Project.team_id == team.id,
            Project.deleted_at.is_(None),
        )
        .order_by(Project.created_at)
    ).all()
    return [(p, role) for p, role in rows]


def create_project(db: Session, actor: User, name: str, members: list[dict]) -> Project:
    """admin 建项目,自动 owner;members 为额外项目成员授权。"""
    require_workspace_admin(db, actor.id)
    team = get_team(db)
    project = Project(team_id=team.id, name=name, created_by=actor.id)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=actor.id, role="owner", created_by=actor.id))
    for m in members:
        _add_member_row(db, project, m["user_id"], m["role"], actor)
    db.commit()
    return project


def get_project(db: Session, user: User, project_id: uuid.UUID) -> tuple[Project, str]:
    project = get_accessible_project(db, user.id, project_id)
    return project, get_project_role(db, user.id, project_id) or "viewer"


def update_project(db: Session, actor: User, project_id: uuid.UUID, name: str) -> Project:
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    name = name.strip()
    if not name:
        raise invalid_request("项目名不能为空")
    project.name = name
    db.commit()
    return project


def list_project_members(db: Session, user: User, project_id: uuid.UUID) -> list[tuple[User, str]]:
    # 项目成员可查看彼此及角色；增删改成员仍由各写操作单独要求 owner。
    get_accessible_project(db, user.id, project_id)
    rows = db.execute(
        select(User, ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at)
    ).all()
    return [(u, role) for u, role in rows]


def list_member_candidates(db: Session, actor: User, project_id: uuid.UUID) -> list[User]:
    """可添加到项目的人选:工作区成员(非 admin)+ 全部 agent,剔除已在项目中的。"""
    get_accessible_project(db, actor.id, project_id, min_level="owner")
    team = get_team(db)
    already = set(
        db.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)).all()
    )
    humans = db.execute(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.team_id == team.id,
            WorkspaceMember.role != "admin",
            User.deleted_at.is_(None),
        )
        .order_by(User.created_at)
    ).scalars().all()
    agents = db.execute(
        select(User).where(User.is_agent.is_(True), User.deleted_at.is_(None)).order_by(User.created_at)
    ).scalars().all()
    return [u for u in [*humans, *agents] if u.id not in already]


def _add_member_row(db: Session, project: Project, user_id: uuid.UUID, role: str, actor: User) -> None:
    if role not in PROJECT_ROLES:
        raise invalid_request("角色不合法")
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise not_found("用户不存在")
    if not target.is_agent:
        team = get_team(db)
        wm = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.team_id == team.id, WorkspaceMember.user_id == user_id
            )
        )
        if wm is None:
            raise invalid_request("该账号不是工作区成员")
    dup = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
        )
    )
    if dup is not None:
        raise conflict("该用户已在项目中")
    db.add(ProjectMember(project_id=project.id, user_id=user_id, role=role, created_by=actor.id))


def add_project_member(
    db: Session, actor: User, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    _add_member_row(db, project, user_id, role, actor)
    db.commit()


def update_project_member_role(
    db: Session, actor: User, project_id: uuid.UUID, user_id: uuid.UUID, role: str
) -> None:
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    if role not in PROJECT_ROLES:
        raise invalid_request("角色不合法")
    pm = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
        )
    )
    if pm is None:
        raise not_found("该用户不在项目中")
    if pm.role == "owner" or role == "owner":
        raise conflict("owner 角色只能通过转让流程修改")
    pm.role = role
    db.commit()


def remove_project_member(db: Session, actor: User, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    pm = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
        )
    )
    if pm is None:
        raise not_found("该用户不在项目中")
    if pm.role == "owner":
        raise conflict("owner 只能通过转让后再移除")
    db.delete(pm)
    db.commit()


def transfer_project_owner(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    password: str,
) -> None:
    """Transfer the single managed owner role after re-authenticating its holder.

    Workspace admins retain their implicit project access, but only the user
    holding an explicit project-owner membership may transfer that membership.
    This keeps the operation tied to the owner being demoted.
    """
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    source = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == actor.id,
            ProjectMember.role == "owner",
        )
    )
    if source is None:
        raise permission_denied("仅项目当前 owner 可以转让")
    if user_id == actor.id:
        raise invalid_request("转让目标必须是其他项目成员")
    target = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == user_id,
        )
    )
    if target is None:
        raise not_found("转让目标不是项目成员")
    if target.role == "owner":
        raise conflict("转让目标已经是 owner")
    if not actor.password_hash or not verify_password(password, actor.password_hash):
        raise permission_denied("当前密码不正确")
    source.role = "editor"
    target.role = "owner"
    db.commit()


def soft_delete_project(db: Session, actor: User, project_id: uuid.UUID) -> None:
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    project.deleted_at = datetime.now(timezone.utc)
    db.commit()
