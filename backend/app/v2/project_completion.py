"""Bounded Web editor lookups within one authorized project."""

import uuid

from sqlalchemy import String, and_, cast, literal, or_, select, union_all
from sqlalchemy.orm import Session

from ..errors import not_found
from ..models import Project, ProjectMember, Requirement, Task, User, WorkspaceMember
from ..services.permissions import get_accessible_project
from ..services.user_profiles import display_name, payload
from .file_models import ProjectFile
from .resource_refs import ResourceKind, ResourceRef
from .wiki import visible_wiki_codes
from .wiki_models import Wiki

LIMIT = 20


def _eligible_people(project: Project, *, include_workspace_admins: bool = False):
    active_members = (
        select(User.id)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(
            ProjectMember.project_id == project.id,
            WorkspaceMember.team_id == project.team_id,
            User.deleted_at.is_(None),
            User.is_agent.is_(False),
        )
    )
    if include_workspace_admins:
        active_members = active_members.union(
            select(User.id).join(WorkspaceMember, WorkspaceMember.user_id == User.id).where(
                WorkspaceMember.team_id == project.team_id, WorkspaceMember.role == "admin",
                User.deleted_at.is_(None), User.is_agent.is_(False),
            )
        )
    return select(User).where(
        User.deleted_at.is_(None),
        or_(User.id.in_(active_members), and_(User.is_agent.is_(True), User.owner_id.in_(active_members))),
    )


def list_assignees(db: Session, actor: User, project_id: uuid.UUID) -> list[dict]:
    project = get_accessible_project(db, actor.id, project_id, min_level="editor")
    people = _eligible_people(project, include_workspace_admins=True).order_by(User.username, User.id)
    return [payload(person) for person in db.scalars(people)]


def _person_candidate(project_id: uuid.UUID, person: User) -> dict:
    person_id = str(person.id)
    return {
        "id": person_id,
        "kind": "agent" if person.is_agent else "member",
        "label": display_name(person),
        "href": ResourceRef(project_id, ResourceKind.PERSON, person_id).path,
        "detail": person.username,
    }


def get_person(db: Session, actor: User, project_id: uuid.UUID, person_id: uuid.UUID) -> dict:
    project = get_accessible_project(db, actor.id, project_id)
    person = db.scalar(_eligible_people(project).where(User.id == person_id))
    if person is None:
        raise not_found("项目人员不存在或无访问权限")
    return _person_candidate(project.id, person)


def _people(db: Session, project: Project, query: str) -> list[dict]:
    stmt = _eligible_people(project)
    if query:
        stmt = stmt.where(or_(
            User.nickname.icontains(query, autoescape=True),
            User.username.icontains(query, autoescape=True),
        ))
    people = db.scalars(stmt.order_by(User.username, User.id).limit(LIMIT))
    return [_person_candidate(project.id, person) for person in people]


def _references(db: Session, project_id: uuid.UUID, query: str) -> list[dict]:
    def candidates(model, kind: str):
        stmt = select(model.code, model.title, literal(kind).label("kind")).where(
            model.project_id == project_id, model.deleted_at.is_(None),
        )
        if query:
            stmt = stmt.where(or_(
                model.title.icontains(query, autoescape=True),
                model.code.icontains(query, autoescape=True),
            ))
        return stmt

    wiki_candidates = candidates(Wiki, "wiki").where(Wiki.code.in_(visible_wiki_codes(project_id)))
    task_candidates = candidates(Task, "task").where(Task.has_active_requirement())
    files = select(cast(ProjectFile.id, String).label("code"), ProjectFile.name.label("title"),
                   literal("file").label("kind")).where(ProjectFile.project_id == project_id, ProjectFile.deleted_at.is_(None))
    if query:
        files = files.where(ProjectFile.name.icontains(query, autoescape=True))
    combined = union_all(candidates(Requirement, "requirement"), wiki_candidates, task_candidates, files).subquery()
    kinds = {"requirement": ResourceKind.REQUIREMENT, "task": ResourceKind.TASK, "wiki": ResourceKind.WIKI, "file": ResourceKind.FILE}
    rows = db.execute(select(combined).order_by(combined.c.title, combined.c.kind, combined.c.code).limit(LIMIT))
    items = []
    for code, title, kind in rows:
        if kind == "file":
            # SQLite stores UUIDs as hex; public hrefs always use their hyphenated spelling.
            code = str(uuid.UUID(code))
        items.append({"id": code, "label": title, "kind": kind, "detail": code,
                      "href": ResourceRef(project_id, kinds[kind], code).path})
    return items


def completion_candidates(db: Session, actor: User, project_id: uuid.UUID, mode: str, query: str) -> list[dict]:
    project = get_accessible_project(db, actor.id, project_id)
    query = query.strip()
    if mode == "people":
        return _people(db, project, query)
    return _references(db, project.id, query)
