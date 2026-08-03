"""任务服务:CRUD + 五态状态机 + 指派/认领/改派(规格书 §3.2 / §5.1,ticket 09)。

所有权规则(已指派任务):仅被指派者本人 / 工作区 admin / 项目 owner 可改状态/改派;
未指派任务任何编辑权者可操作。状态流转走通用 set_task_status(任意目标态自由流转,
无前置校验);任务状态变化不影响需求状态(自动流转已删除,需求状态全手动)。
认领用条件 UPDATE 原子化,并发竞争败者得 conflict。
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import ProjectMember, Requirement, Task, User
from .pagination import page_result
from .permissions import get_accessible_project, get_project_role, is_admin, require_project_role
from .polymorphic import record_activity
from .workflow import TERMINAL, assert_status_valid

# update_task 的 requirement_id 哨兵:未传 = 不变;None = 显式解除
_UNSET = object()


def _task_dict(db: Session, t: Task) -> dict:
    assignee = db.get(User, t.assignee_id) if t.assignee_id else None
    return {
        "id": str(t.id),
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "project_id": str(t.project_id),
        "requirement_id": str(t.requirement_id) if t.requirement_id else None,
        "assignee_id": str(t.assignee_id) if t.assignee_id else None,
        "assignee": assignee.username if assignee else None,
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _get_visible(db: Session, user: User, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)))
    if task is None:
        raise not_found("任务不存在")
    get_accessible_project(db, user.id, task.project_id, min_level="viewer")
    return task


def _get_editable(db: Session, actor: User, task_id: uuid.UUID) -> Task:
    task = _get_visible(db, actor, task_id)
    require_project_role(db, actor.id, task.project_id, min_level="editor")
    return task


def _require_owner(db: Session, actor: User, task: Task) -> None:
    """已指派任务的所有权守卫;未指派任何编辑权者可操作。"""
    if task.assignee_id is None:
        return
    if task.assignee_id == actor.id:
        return
    if is_admin(db, actor.id) or get_project_role(db, actor.id, task.project_id) == "owner":
        return
    raise permission_denied("已指派任务仅被指派者或管理员可操作")


def _check_assignee(db: Session, project_id: uuid.UUID, assignee_id: uuid.UUID) -> User:
    assignee = db.get(User, assignee_id)
    if assignee is None or assignee.deleted_at is not None:
        raise not_found("被指派者不存在")
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == assignee_id
        )
    )
    if member is None:
        raise invalid_request("被指派者不是项目成员")
    return assignee


def _check_requirement(db: Session, project_id: uuid.UUID, requirement_id: uuid.UUID) -> None:
    """需求须存在、未删除、且与任务同项目(跨项目拒绝)。"""
    requirement = db.scalar(
        select(Requirement).where(
            Requirement.id == requirement_id, Requirement.deleted_at.is_(None)
        )
    )
    if requirement is None:
        raise not_found("需求不存在")
    if requirement.project_id != project_id:
        raise invalid_request("任务所属项目与需求不一致")


def create_task(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    title: str,
    description: str | None = None,
    requirement_id: uuid.UUID | None = None,
    assignee_id: uuid.UUID | None = None,
) -> Task:
    title = title.strip()
    if not title:
        raise invalid_request("标题不能为空")
    require_project_role(db, actor.id, project_id, min_level="editor")
    requirement = None
    if requirement_id is not None:
        _check_requirement(db, project_id, requirement_id)
    if assignee_id is not None:
        _check_assignee(db, project_id, assignee_id)
    task = Task(
        project_id=project_id,
        title=title,
        description=description,
        requirement_id=requirement_id,
        assignee_id=assignee_id,
        created_by=actor.id,
    )
    db.add(task)
    db.flush()
    record_activity(db, project_id, actor.id, "task", task.id, "create", "创建任务")
    db.commit()
    return task


def get_task(db: Session, user: User, task_id: uuid.UUID) -> Task:
    return _get_visible(db, user, task_id)


def list_tasks(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    requirement_id: uuid.UUID | None,
    assignee_id: uuid.UUID | None,
    status: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    filters = {
        "project_id": str(project_id),
        "requirement_id": str(requirement_id) if requirement_id else None,
        "assignee_id": str(assignee_id) if assignee_id else None,
        "status": status,
    }
    from .pagination import decode_cursor

    offset = decode_cursor(filters, cursor)
    stmt = select(Task).where(Task.project_id == project_id, Task.deleted_at.is_(None))
    if requirement_id:
        stmt = stmt.where(Task.requirement_id == requirement_id)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if status:
        stmt = stmt.where(Task.status == status)
    rows = db.scalars(stmt.order_by(Task.created_at).offset(offset).limit(limit)).all()
    items = [_task_dict(db, t) for t in rows]
    return page_result(items, offset, limit, filters)


def update_task(
    db: Session,
    actor: User,
    task_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    requirement_id: object = _UNSET,
) -> Task:
    """更新任务元数据;requirement_id 可设/可换/可解除(null=解除)。

    requirement_id 权限与改状态同规则(已指派仅本人/工作区 admin/项目 owner,
    未指派任意编辑权);校验需求同项目且未删除。
    """
    task = _get_editable(db, actor, task_id)
    if title is not None:
        title = title.strip()
        if not title:
            raise invalid_request("标题不能为空")
        task.title = title
    if description is not None:
        task.description = description
    summary = "更新任务"
    if requirement_id is not _UNSET:
        _require_owner(db, actor, task)
        rid = requirement_id if requirement_id is None else uuid.UUID(str(requirement_id))
        if rid != task.requirement_id:
            if rid is not None:
                _check_requirement(db, task.project_id, rid)
            task.requirement_id = rid
            summary = "关联需求" if rid else "解除需求关联"
    record_activity(db, task.project_id, actor.id, "task", task.id, "update", summary)
    db.commit()
    return task


def set_task_status(
    db: Session, actor: User, task_id: uuid.UUID, target: str
) -> Task:
    """通用改状态:任意目标态自由流转,无任何前置校验;已指派任务走所有权守卫。"""
    task = _get_editable(db, actor, task_id)
    _require_owner(db, actor, task)
    assert_status_valid(task.status, target, "任务")
    old = task.status
    task.status = target
    record_activity(
        db,
        task.project_id,
        actor.id,
        "task",
        task.id,
        "status",
        f"{old} → {target}",
    )
    db.commit()
    return task


def assign_task(db: Session, actor: User, task_id: uuid.UUID, assignee_id: uuid.UUID) -> Task:
    """未指派任务任何编辑权者可指派;已指派仅本人/管理员可改派。"""
    task = _get_editable(db, actor, task_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法改派")
    if task.assignee_id is not None:
        _require_owner(db, actor, task)
    assignee = _check_assignee(db, task.project_id, assignee_id)
    task.assignee_id = assignee_id
    record_activity(
        db, task.project_id, actor.id, "task", task.id, "assign", f"指派给 {assignee.username}"
    )
    db.commit()
    return task


def claim_task(db: Session, actor: User, task_id: uuid.UUID) -> Task:
    """未指派任务的认领;条件 UPDATE 原子化,并发竞争败者得 conflict。"""
    task = _get_editable(db, actor, task_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法认领")
    try:
        result = db.execute(
            update(Task)
            .where(Task.id == task.id, Task.assignee_id.is_(None))
            .values(assignee_id=actor.id)
        )
    except OperationalError:
        db.rollback()
        raise conflict("并发认领冲突,请重试")
    if result.rowcount != 1:
        db.rollback()
        raise conflict("任务已被认领")
    db.flush()
    record_activity(db, task.project_id, actor.id, "task", task.id, "claim", "认领任务")
    db.commit()
    return task


def unassign_task(db: Session, actor: User, task_id: uuid.UUID) -> Task:
    task = _get_editable(db, actor, task_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法解除指派")
    _require_owner(db, actor, task)
    task.assignee_id = None
    record_activity(db, task.project_id, actor.id, "task", task.id, "unassign", "解除指派")
    db.commit()
    return task


def cancel_task(db: Session, actor: User, task_id: uuid.UUID) -> Task:
    """取消任务:set_task_status("cancelled") 便捷封装。"""
    return set_task_status(db, actor, task_id, "cancelled")


def delete_task(db: Session, actor: User, task_id: uuid.UUID) -> None:
    task = _get_editable(db, actor, task_id)
    _require_owner(db, actor, task)
    task.deleted_at = _now()
    record_activity(db, task.project_id, actor.id, "task", task.id, "delete", "删除任务")
    db.commit()


def restore_task(db: Session, actor: User, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id))
    if task is None or task.deleted_at is None:
        raise not_found("已删除的任务不存在")
    require_project_role(db, actor.id, task.project_id, min_level="editor")
    task.deleted_at = None
    record_activity(db, task.project_id, actor.id, "task", task.id, "restore", "恢复任务")
    db.commit()
    return task


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
