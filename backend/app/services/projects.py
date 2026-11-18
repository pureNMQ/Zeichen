"""项目服务:建项目(admin)、列表(admin 全量/member 已加入)、项目成员管理(owner/admin)。"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import case, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Attachment, Document, Project, ProjectMember, Repository, Requirement, Task, User, WorkspaceMember
from .pagination import decode_cursor, encode_cursor
from .permissions import effective_user_id, get_accessible_project, get_project_role, get_team, is_admin, require_workspace_admin
from .user_profiles import payload as profile_payload
from ..security import verify_password

PROJECT_ROLES = ("owner", "editor", "viewer")


def list_projects(db: Session, user: User) -> list[tuple[Project, str]]:
    team = get_team(db)
    # 附属 agent 按主人身份列出项目(判权统一走 permissions 解析)
    effective_id = effective_user_id(db, user.id)
    if effective_id is None:
        return []
    if is_admin(db, effective_id):
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
            ProjectMember.user_id == effective_id,
            Project.team_id == team.id,
            Project.deleted_at.is_(None),
        )
        .order_by(Project.created_at)
    ).all()
    return [(p, role) for p, role in rows]


def project_roster_summaries(db: Session, project_ids: list[uuid.UUID]) -> dict:
    owner = case((ProjectMember.role == "owner", func.coalesce(func.nullif(func.trim(User.nickname), ""), User.username)))
    rows = db.execute(
        select(ProjectMember.project_id, func.count(User.id), func.max(owner))
        .join(User, User.id == ProjectMember.user_id)
        .join(Project, Project.id == ProjectMember.project_id)
        .join(WorkspaceMember, (WorkspaceMember.user_id == User.id) & (WorkspaceMember.team_id == Project.team_id))
        .where(ProjectMember.project_id.in_(project_ids), User.deleted_at.is_(None), User.is_agent.is_(False))
        .group_by(ProjectMember.project_id)
    )
    return {project_id: (count, owner_name) for project_id, count, owner_name in rows}


def project_summary(project: Project, role: str) -> dict:
    return {"id": str(project.id), "name": project.name, "description": project.description,
            "created_at": project.created_at.isoformat(), "my_role": role}


def project_directory(db: Session, actor: User) -> list[dict]:
    projects = list_projects(db, actor)
    rosters = project_roster_summaries(db, [project.id for project, _ in projects])
    items = []
    for project, role in projects:
        member_count, owner_name = rosters.get(project.id, (0, None))
        items.append({**project_summary(project, role), "member_count": member_count, "owner_name": owner_name})
    return items


def create_project(db: Session, actor: User, name: str, members: list[dict], description: str = "") -> Project:
    """admin 建项目,自动 owner;members 为额外项目成员授权。"""
    require_workspace_admin(db, actor.id)
    team = get_team(db)
    if not name.strip():
        raise invalid_request("项目名不能为空")
    project = Project(team_id=team.id, name=name.strip(), description=description.strip(), created_by=actor.id)
    db.add(project)
    db.flush()
    # The human owns the project; preserve the acting identity in the audit fields.
    db.add(ProjectMember(project_id=project.id, user_id=effective_user_id(db, actor.id),
                         role="owner", created_by=actor.id))
    for m in members:
        _add_member_row(db, project, m["user_id"], m["role"], actor)
    db.commit()
    return project


def get_project(db: Session, user: User, project_id: uuid.UUID) -> tuple[Project, str]:
    project = get_accessible_project(db, user.id, project_id)
    return project, get_project_role(db, user.id, project_id) or "viewer"


def update_project(db: Session, actor: User, project_id: uuid.UUID, name: str | None = None,
                   description: str | None = None) -> Project:
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    if name is None and description is None:
        raise invalid_request("请填写需要修改的项目信息")
    if name is not None:
        if not name.strip():
            raise invalid_request("项目名不能为空")
        project.name = name.strip()
    if description is not None:
        project.description = description.strip()
    db.commit()
    return project


def _workspace_people(project: Project):
    return (
        select(User, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            WorkspaceMember.team_id == project.team_id,
            User.is_agent.is_(False),
            User.deleted_at.is_(None),
        )
    )


def list_project_members(db: Session, user: User, project_id: uuid.UUID) -> list[tuple[User, str, str]]:
    project = get_accessible_project(db, user.id, project_id)
    rows = db.execute(
        _workspace_people(project)
        .add_columns(ProjectMember.role)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == project.id)
        .order_by(ProjectMember.created_at, User.id)
    )
    return [(person, workspace_role, project_role) for person, workspace_role, project_role in rows]


def list_member_candidates(db: Session, actor: User, project_id: uuid.UUID) -> list[tuple[User, str]]:
    """列出尚未在项目名册中登记的有效工作区人类成员，包括管理员。"""
    project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    registered = select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
    rows = db.execute(
        _workspace_people(project)
        .where(User.id.not_in(registered))
        .order_by(User.created_at, User.id)
    )
    return [(person, workspace_role) for person, workspace_role in rows]


def roster(db: Session, actor: User, project_id: uuid.UUID) -> list[dict]:
    principal_id = effective_user_id(db, actor.id)
    return [{**profile_payload(user), "role": role, "workspace_role": workspace_role,
             "is_current_user": user.id == principal_id}
            for user, workspace_role, role in list_project_members(db, actor, project_id)]


def eligible_people(db: Session, actor: User, project_id: uuid.UUID) -> list[dict]:
    return [{**profile_payload(user), "workspace_role": role}
            for user, role in list_member_candidates(db, actor, project_id)]


def _add_member_row(db: Session, project: Project, user_id: uuid.UUID, role: str, actor: User) -> None:
    if role not in ("viewer", "editor"):
        raise invalid_request("角色不合法")
    if db.scalar(_workspace_people(project).where(User.id == user_id)) is None:
        target = db.get(User, user_id)
        if target is None or target.deleted_at is not None:
            raise not_found("用户不存在")
        if target.is_agent:
            raise invalid_request("附属 Agent 不单独加入项目,其权限随主人")
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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if db.scalar(select(ProjectMember.id).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )):
            raise conflict("该用户已在项目中")
        raise


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
            ProjectMember.user_id.in_(_workspace_people(project).with_only_columns(User.id)),
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
    project.deleted_by = actor.id
    db.commit()


def _owned_deleted_projects(db: Session, actor: User):
    team = get_team(db)
    stmt = select(Project).where(Project.team_id == team.id, Project.deleted_at.is_not(None))
    principal_id = effective_user_id(db, actor.id)
    if principal_id is None:
        return stmt.where(False)
    if is_admin(db, principal_id):
        return stmt
    return stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(
        ProjectMember.user_id == principal_id, ProjectMember.role == "owner"
    )


def _trash_item(project: Project) -> dict:
    return {
        "id": str(project.id),
        "name": project.name,
        "deleted_at": project.deleted_at.isoformat(),
        "deleted_by": str(project.deleted_by) if project.deleted_by else None,
    }


def list_deleted_projects(
    db: Session, actor: User, *, q: str = "", cursor: str | None = None, limit: int = 20,
) -> dict:
    q = q.strip()
    if not 1 <= limit <= 100 or len(q) > 128:
        raise invalid_request("每页 1 到 100 项，名称筛选最多 128 字")
    filters = {"actor": str(actor.id), "kind": "project_trash", "q": q}
    offset = decode_cursor(filters, cursor)
    stmt = _owned_deleted_projects(db, actor)
    if q:
        stmt = stmt.where(Project.name.icontains(q, autoescape=True))
    projects = list(db.scalars(stmt.order_by(Project.deleted_at.desc(), Project.id).offset(offset).limit(limit + 1)))
    return {
        "items": [_trash_item(project) for project in projects[:limit]],
        "next_cursor": encode_cursor(filters, offset + limit, limit) if len(projects) > limit else None,
    }


def project_delete_impact(db: Session, actor: User, project_id: uuid.UUID, *, deleted: bool = False) -> dict:
    if deleted:
        project = db.scalar(_owned_deleted_projects(db, actor).where(Project.id == project_id))
        if project is None:
            raise not_found("已删除项目不存在或无权限")
    else:
        project = get_accessible_project(db, actor.id, project_id, min_level="owner")
    counts = {}
    for name, model in (
        ("requirements", Requirement), ("tasks", Task), ("wiki", Document),
        ("attachments", Attachment), ("repositories", Repository),
    ):
        query = select(func.count()).select_from(model).where(
            model.project_id == project_id, model.deleted_at.is_(None)
        )
        if model is Task:
            query = query.join(Requirement, (Requirement.project_id == Task.project_id)
                               & (Requirement.code == Task.requirement_id)).where(Requirement.deleted_at.is_(None))
        counts[name] = db.scalar(query)
    metadata = _trash_item(project) if deleted else {"id": str(project.id), "name": project.name}
    return {**metadata, "affected": counts}


def restore_project(db: Session, actor: User, project_id: uuid.UUID) -> dict:
    project = db.scalar(_owned_deleted_projects(db, actor).where(Project.id == project_id))
    if project is None:
        raise not_found("已删除项目不存在或无权限")
    recovered = db.execute(
        update(Project).where(Project.id == project_id, Project.deleted_at.is_not(None))
        .values(deleted_at=None, deleted_by=None)
    ).rowcount
    if recovered != 1:
        raise conflict("项目删除状态已变化，请刷新")
    db.commit()
    return {"id": str(project_id), "restored": True}
