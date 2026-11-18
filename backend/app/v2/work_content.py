"""Versioned Markdown shared by human and agent work-item editors."""

from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Requirement, Task, User
from ..services.permissions import require_project_role
from .commands import execute_once
from .markdown_refs import extract_markdown_refs
from .notifications import emit_markdown_notifications
from .resource_refs import ResourceKind, ResourceRef
from ..services.polymorphic import record_activity
from .work_content_models import WorkReference, WorkVersion

WorkKind = Literal["requirements", "tasks"]


def document_title(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 256 or "\x00" in value:
        raise invalid_request("标题须包含 1 至 256 个有效字符")
    return value


def markdown(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise invalid_request("正文含无效字符")
    return value


def create(db: Session, actor: User, project_id: UUID, kind: WorkKind, title: str, description: str | None,
           request_id: UUID | None, *, requirement_id: str | None = None, assignee_id: UUID | None = None) -> dict:
    """Issue the same creation receipt on retries, atomically with identity allocation and v1."""
    from ..services.requirements import _requirement_dict, create_requirement
    from ..services.tasks import _task_dict, create_task

    require_project_role(db, actor.id, project_id, min_level="editor")
    title = document_title(title)
    description = markdown(description)

    def apply():
        if kind == "requirements":
            result = _requirement_dict(db, create_requirement(db, actor, project_id, title, description, commit=False))
        else:
            task = create_task(db, actor, project_id, title, description, requirement_id, assignee_id, commit=False)
            result = _task_dict(db, task)
        # The caller already has the exact normalized inputs; never duplicate Markdown in a receipt.
        return {key: value for key, value in result.items() if key not in {"title", "description"}}

    try:
        receipt = apply() if request_id is None else execute_once(db, project_id=project_id, actor_id=actor.id,
            request_id=request_id, operation=f"{kind}.create", payload={
                "title": title, "description": description, "requirement_id": requirement_id,
                "assignee_id": str(assignee_id) if assignee_id else None,
            }, apply=apply)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**receipt, "title": title, "description": description}


def notify_body_mentions(db: Session, item: Requirement | Task, actor_id: UUID, previous_body: str | None = None) -> None:
    if not item.description or item.description == previous_body:
        return
    kind = ResourceKind.TASK if isinstance(item, Task) else ResourceKind.REQUIREMENT
    emit_markdown_notifications(db, actor_id, source=ResourceRef(item.project_id, kind, item.code),
                                source_version=item.version, body=item.description, previous_body=previous_body)


def snapshot(db: Session, item: Requirement | Task, actor_id: UUID | None) -> None:
    is_task = isinstance(item, Task)
    rev = WorkVersion(
        project_id=item.project_id, code=item.code, version=item.version,
        requirement_code=item.requirement_id if is_task else item.code,
        task_code=item.code if is_task else None, title=item.title,
        description=item.description, created_by=actor_id,
    )
    db.add(rev)
    db.flush()
    db.add_all([WorkReference(project_id=item.project_id, code=item.code, version=item.version,
                              target_kind=r.kind.value, target_id=r.identifier)
                for r in extract_markdown_refs(item.description or "", item.project_id)])


def revise(db: Session, actor: User, item: Requirement | Task, title: str | None,
           description: str | None, expected_version: int | None, *, restored_from: int | None = None) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise invalid_request("请提供读取正文时的 expected_version")
    previous_body = item.description
    new_title = item.title if title is None else document_title(title)
    body = item.description if description is None and restored_from is None else markdown(description)
    model = type(item)
    constraints = [model.project_id == item.project_id, model.code == item.code,
                   model.deleted_at.is_(None), model.version == expected_version]
    if isinstance(item, Task):
        constraints.append(Task.has_active_requirement())
    count = db.execute(update(model).where(*constraints).values(
        title=new_title, description=body, version=expected_version + 1,
    ).execution_options(synchronize_session=False)).rowcount
    if count != 1:
        raise conflict("正文版本已变更，请保留草稿并重新读取最新版本")
    db.refresh(item)
    snapshot(db, item, actor.id)
    if restored_from is None:
        notify_body_mentions(db, item, actor.id, previous_body)
    is_task = isinstance(item, Task)
    summary = f"保存正文版本 {item.version}" if restored_from is None else f"恢复正文版本 {restored_from} 为版本 {item.version}"
    record_activity(db, item.project_id, actor.id, "task" if is_task else "requirement", item.code, "update", summary)


def _item(db: Session, actor: User, project_id: UUID, kind: WorkKind, code: str):
    from ..services.requirements import get_requirement
    from ..services.tasks import get_task

    getter = get_task if kind == "tasks" else get_requirement
    return getter(db, actor, code, project_id=project_id)


def _revision_query(item: Requirement | Task, *, full: bool = False):
    v = WorkVersion
    author_name = func.coalesce(func.nullif(func.trim(User.nickname), ""), User.username)
    query = select(v.version, v.title, v.created_by, v.created_at,
                   author_name.label("actor_name"), User.is_agent.label("actor_is_agent"))
    if full:
        query = query.add_columns(v.description)
    return query.outerjoin(User, User.id == v.created_by).where(
        v.project_id == item.project_id, v.code == item.code)


def _fields(row, *, full: bool = False) -> dict:
    data = dict(version=row.version, title=row.title, actor_id=str(row.created_by) if row.created_by else None,
                actor_name=row.actor_name, actor_is_agent=row.actor_is_agent, created_at=row.created_at.isoformat())
    if full:
        data["description"] = row.description
    return data


def versions(db: Session, actor: User, project_id: UUID, kind: WorkKind, code: str,
             before: int | None = None, limit: int = 50) -> dict:
    item = _item(db, actor, project_id, kind, code)
    if not 1 <= limit <= 100 or (before is not None and before < 1):
        raise invalid_request("版本分页参数无效")
    v = WorkVersion
    query = _revision_query(item)
    if before is not None:
        query = query.where(v.version < before)
    rows = db.execute(query.order_by(v.version.desc()).limit(limit + 1)).all()
    return {"items": [_fields(row) for row in rows[:limit]], "next_before": rows[limit-1].version if len(rows) > limit else None}


def _version(db: Session, item: Requirement | Task, number: int) -> WorkVersion:
    row = db.get(WorkVersion, (item.project_id, item.code, number))
    if row is None:
        raise not_found("正文版本不存在")
    return row


def version(db: Session, actor: User, project_id: UUID, kind: WorkKind, code: str, number: int) -> dict:
    item = _item(db, actor, project_id, kind, code)
    row = db.execute(_revision_query(item, full=True).where(WorkVersion.version == number)).one_or_none()
    if row is None:
        raise not_found("正文版本不存在")
    return _fields(row, full=True)


def restore(db: Session, actor: User, project_id: UUID, kind: WorkKind, code: str,
            number: int, expected_version: int) -> dict:
    from ..services.requirements import _requirement_dict
    from ..services.tasks import _task_dict

    item = _item(db, actor, project_id, kind, code)
    require_project_role(db, actor.id, project_id, min_level="editor")
    previous = _version(db, item, number)
    revise(db, actor, item, previous.title, previous.description, expected_version, restored_from=number)
    db.commit()
    return (_task_dict if isinstance(item, Task) else _requirement_dict)(db, item)
