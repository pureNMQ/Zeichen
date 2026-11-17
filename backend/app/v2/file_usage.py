"""Discover authorized uses and manage explicit links without changing file bytes."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, case, delete, literal, select, tuple_, union
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..errors import AppError, invalid_request, not_found
from ..models import Project, Requirement, Task
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .file_models import FileAssociation, ProjectFile
from .files import get_file, require_file_access
from .page_cursor import decode_position, encode_position, scope_key
from .resource_refs import ResourceKind, ResourceRef, parse_uuid
from .wiki import visible_wiki_codes
from .wiki_models import Wiki, WikiReference, WikiVersion


class TargetKind(StrEnum):
    PROJECT = "project"
    REQUIREMENT = "requirements"
    TASK = "tasks"
    WIKI = "wiki"


class UsageItem(BaseModel):
    href: str
    label: str
    kind: str
    current: bool


class UsagePage(BaseModel):
    items: list[UsageItem]
    next_cursor: str | None


class AssociationReceipt(BaseModel):
    project_id: UUID
    file_id: UUID
    target_kind: TargetKind
    target_id: str
    linked: bool
    changed: bool


_ASSOC = FileAssociation
_MODELS = {TargetKind.REQUIREMENT: Requirement, TargetKind.TASK: Task, TargetKind.WIKI: Wiki}
_USAGE_LABELS = {TargetKind.PROJECT: "project", TargetKind.REQUIREMENT: "requirement", TargetKind.TASK: "task", TargetKind.WIKI: "wiki"}


def _task_has_active_parent():
    return select(Requirement.code).where(
        Requirement.project_id == Task.project_id, Requirement.code == Task.requirement_id, Requirement.deleted_at.is_(None),
    ).exists()


def _active_target(kind: TargetKind, project_id: UUID, allowed_wikis=None):
    model = _MODELS[kind]
    if kind == TargetKind.WIKI:
        return Wiki.code.in_(allowed_wikis if allowed_wikis is not None else visible_wiki_codes(project_id))
    if kind == TargetKind.TASK:
        return and_(Task.deleted_at.is_(None), _task_has_active_parent())
    return model.deleted_at.is_(None)


def _association_uses(project_id: UUID, file_id: UUID, allowed_wikis):
    predicates = (_ASSOC.project_id == project_id, _ASSOC.file_id == file_id)
    yield select(literal(TargetKind.PROJECT.value).label("kind"), _ASSOC.target_id,
                 Project.name.label("label"), literal(0).label("version"), literal(True).label("current")).select_from(_ASSOC).join(
        Project, Project.id == _ASSOC.project_id,
    ).where(*predicates, _ASSOC.target_kind == TargetKind.PROJECT.value, _ASSOC.target_id == str(project_id), Project.deleted_at.is_(None))

    for kind, model in _MODELS.items():
        version = Wiki.version_no if kind == TargetKind.WIKI else literal(0)
        yield select(literal(kind.value).label("kind"), _ASSOC.target_id, model.title.label("label"),
                     version.label("version"), literal(True).label("current")).select_from(_ASSOC).join(
            model, and_(model.project_id == _ASSOC.project_id, model.code == _ASSOC.target_id),
        ).where(*predicates, _ASSOC.target_kind == kind.value, _active_target(kind, project_id, allowed_wikis))


def _wiki_uses(project_id: UUID, file_id: UUID, allowed_wikis, include_history: bool):
    current = Wiki.version_no == WikiReference.version_no
    statement = select(
        literal(TargetKind.WIKI.value).label("kind"), WikiReference.wiki_code.label("target_id"),
        case((current, Wiki.title), else_=WikiVersion.title).label("label"),
        WikiReference.version_no.label("version"), current.label("current"),
    ).select_from(WikiReference).join(Wiki, and_(
        Wiki.project_id == WikiReference.project_id, Wiki.code == WikiReference.wiki_code,
    )).join(WikiVersion, and_(
        WikiVersion.project_id == WikiReference.project_id, WikiVersion.wiki_code == WikiReference.wiki_code,
        WikiVersion.version_no == WikiReference.version_no,
    )).where(
        WikiReference.project_id == project_id, WikiReference.target_kind == ResourceKind.FILE.value,
        WikiReference.target_id == str(file_id), WikiReference.wiki_code.in_(allowed_wikis),
    )
    return statement if include_history else statement.where(current)


def _href(project_id: UUID, kind: TargetKind, target_id: str) -> str:
    if kind == TargetKind.PROJECT:
        if parse_uuid(target_id, "target_id") != project_id:
            raise not_found("关联目标不存在或不可见")
        return f"/projects/{project_id}"
    return ResourceRef(project_id, ResourceKind(kind.value), target_id).path


def list_usage(
    db: Session, actor_id: UUID, project_id: UUID, file_id: UUID, *, include_history: bool = False,
    cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
) -> UsagePage:
    get_file(db, actor_id, project_id, file_id)
    if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
        raise invalid_request(f"每页使用位置须为 1 至 {MAX_PAGE_SIZE} 条")
    scope = scope_key("files.usage", str(actor_id), str(project_id), str(file_id), include_history, limit)
    position = decode_position(scope, cursor)
    allowed_wikis = visible_wiki_codes(project_id)
    uses = union(*_association_uses(project_id, file_id, allowed_wikis),
                 _wiki_uses(project_id, file_id, allowed_wikis, include_history)).subquery()
    order = (uses.c.kind, uses.c.target_id, -uses.c.version)
    statement = select(uses)
    if position is not None:
        if (len(position) != 3 or not all(isinstance(value, str) for value in position[:2])
                or type(position[2]) is not int or not -2_147_483_647 <= position[2] <= 0):
            raise invalid_request("文件使用位置游标无效")
        try:
            kind = TargetKind(position[0])
            _href(project_id, kind, position[1])
        except (ValueError, AppError) as exc:
            raise invalid_request("文件使用位置游标无效") from exc
        statement = statement.where(tuple_(*order) > tuple_(*position))
    rows = list(db.execute(statement.order_by(*order).limit(limit + 1)))
    items = []
    for row in rows[:limit]:
        kind = TargetKind(row.kind)
        href, label = _href(project_id, kind, row.target_id), row.label
        if kind == TargetKind.WIKI and not row.current:
            href = f"{href}?version={row.version}"
            label = f"{label} · v{row.version}"
        items.append(UsageItem(href=href, label=label, kind=_USAGE_LABELS[kind], current=row.current))
    last = rows[limit - 1] if len(rows) > limit else None
    return UsagePage(items=items, next_cursor=encode_position(scope, [last.kind, last.target_id, -last.version]) if last else None)


def set_association(
    db: Session, actor_id: UUID, project_id: UUID, file_id: UUID, *, kind: TargetKind, target_id: str, linked: bool,
) -> AssociationReceipt:
    require_file_access(db, actor_id, project_id, edit=True)
    existing = db.scalar(select(ProjectFile.id).where(
        ProjectFile.project_id == project_id, ProjectFile.id == file_id, ProjectFile.deleted_at.is_(None),
    ).with_for_update())
    if existing is None:
        raise not_found("文件不存在或不可用")
    _href(project_id, kind, target_id)
    if kind != TargetKind.PROJECT:
        model = _MODELS[kind]
        visible = db.scalar(select(model.code).where(
            model.project_id == project_id, model.code == target_id, _active_target(kind, project_id),
        ))
        if visible is None:
            raise not_found("关联目标不存在或不可见")
    if linked:
        insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[db.get_bind().dialect.name]
        statement = insert(_ASSOC).values(
            project_id=project_id, file_id=file_id, target_kind=kind.value, target_id=target_id, created_by=actor_id,
        ).on_conflict_do_nothing()
    else:
        statement = delete(_ASSOC).where(_ASSOC.project_id == project_id, _ASSOC.file_id == file_id,
                                         _ASSOC.target_kind == kind.value, _ASSOC.target_id == target_id)
    changed = db.scalar(statement.returning(_ASSOC.file_id)) is not None
    return AssociationReceipt(project_id=project_id, file_id=file_id, target_kind=kind, target_id=target_id,
                              linked=linked, changed=changed)
