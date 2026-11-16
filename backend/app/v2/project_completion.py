"""Bounded Web editor lookups within one authorized project."""

import uuid

from sqlalchemy import and_, literal, or_, select, union_all
from sqlalchemy.orm import Session

from ..errors import not_found
from ..models import Document, Project, ProjectMember, Requirement, User, WorkspaceMember
from ..services.permissions import get_accessible_project
from ..services.user_profiles import display_name
from .resource_refs import ResourceKind, ResourceRef

LIMIT = 20


def _eligible_people(project: Project):
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
    return select(User).where(
        User.deleted_at.is_(None),
        or_(User.id.in_(active_members), and_(User.is_agent.is_(True), User.owner_id.in_(active_members))),
    )


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

    combined = union_all(candidates(Requirement, "requirement"), candidates(Document, "wiki")).subquery()
    rows = db.execute(select(combined).order_by(combined.c.title, combined.c.kind, combined.c.code).limit(LIMIT))
    return [
        {
            "id": code,
            "label": title,
            "kind": kind,
            "detail": code,
            "href": ResourceRef(
                project_id, ResourceKind.REQUIREMENT if kind == "requirement" else ResourceKind.WIKI, code
            ).path,
        }
        for code, title, kind in rows
    ]


def completion_candidates(db: Session, actor: User, project_id: uuid.UUID, mode: str, query: str) -> list[dict]:
    project = get_accessible_project(db, actor.id, project_id)
    query = query.strip()
    if mode == "people":
        return _people(db, project, query)
    return _references(db, project.id, query)
