"""Tasks have an immutable parent requirement and a project-scoped REQ-n-Tm code."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, defer

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Requirement, Task, User
from ..v2.resource_refs import ResourceKind, ResourceRef
from ..v2.timeline import record_system_event
from .requirement_board import remember_assignees
from .labels import STATUS_CN
from .pagination import page_result
from .permissions import get_accessible_project, get_project_role, is_admin, require_project_role
from .polymorphic import record_activity
from ..v2 import work_content
from .user_profiles import avatar_url, display_name
from .workflow import TERMINAL, assert_status_valid


def _task_dict(db: Session, t: Task, *, excerpt: tuple[str | None, bool] | None = None) -> dict:
    assignee = db.get(User, t.assignee_id) if t.assignee_id else None
    return {
        "id": t.code,
        "title": t.title,
        "description": excerpt[0] if excerpt else t.description,
        **({"description_truncated": excerpt[1]} if excerpt else {}),
        "version": t.version,
        "status": t.status,
        "project_id": str(t.project_id),
        "requirement_id": t.requirement_id,
        "assignee_id": str(t.assignee_id) if t.assignee_id else None,
        "assignee": display_name(assignee) if assignee else None,
        "assignee_username": assignee.username if assignee else None,
        "assignee_avatar": avatar_url(assignee),
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat(),
    }


def _get_visible(db: Session, user: User, task_id: str, project_id: uuid.UUID | None = None) -> Task:
    from .short_codes import require_valid_code
    from .short_code_lookup import resolve_by_code

    require_valid_code("task", task_id)
    task, _project = resolve_by_code(db, user, "task", task_id, project_id=project_id)
    get_accessible_project(db, user.id, task.project_id, min_level="viewer")
    return task


def _get_editable(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    task = _get_visible(db, actor, task_id, project_id)
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
    # ADR 0004:附属 agent 随主人判权,可被指派(主人有项目角色即可)
    if get_project_role(db, assignee_id, project_id) is None:
        raise invalid_request("被指派者不是项目成员")
    return assignee


def _check_requirement(db: Session, project_id: uuid.UUID, requirement_id: str) -> None:
    """需求须存在、未删除，且与任务同项目。"""
    from .requirements import get_requirement_in_project
    from .short_codes import require_valid_code

    require_valid_code("requirement", requirement_id)
    requirement = get_requirement_in_project(db, project_id, requirement_id)
    if requirement.project_id != project_id:  # pragma: no cover - 项目内查询已约束
        raise invalid_request("任务所属项目与需求不一致")


def create_task(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    title: str,
    description: str | None = None,
    requirement_id: str | None = None,
    assignee_id: uuid.UUID | None = None,
    *, commit: bool = True,
) -> Task:
    """为指定需求分配下一个任务短码。"""
    from .short_codes import allocate_code

    title = work_content.document_title(title)
    if requirement_id is None:
        raise invalid_request("任务必须挂需求,请指定 requirement_id")
    require_project_role(db, actor.id, project_id, min_level="editor")
    description = work_content.markdown(description)
    _check_requirement(db, project_id, requirement_id)
    if assignee_id is not None:
        _check_assignee(db, project_id, assignee_id)
    code = allocate_code(db, project_id, "task", requirement_code=requirement_id)
    task = Task(
        project_id=project_id,
        code=code,
        title=title,
        description=description,
        requirement_id=requirement_id,
        assignee_id=assignee_id,
        created_by=actor.id,
    )
    db.add(task)
    db.flush()
    work_content.snapshot(db, task, actor.id)
    work_content.notify_body_mentions(db, task, actor.id)
    record_activity(db, project_id, actor.id, "task", code, "create", "创建任务")
    if commit:
        db.commit()
    return task


def get_task(
    db: Session, user: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    return _get_visible(db, user, task_id, project_id)


def list_tasks(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    requirement_id: str | None,
    assignee_id: uuid.UUID | None,
    status: str | list[str] | None,
    cursor: str | None,
    limit: int,
    updated_within_days: int | str | None = None,
    keyword: str | None = None,
) -> dict:
    """任务列表:多维筛选(状态/指派/需求) + updated_within_days 时间窗口 + keyword。

    筛选在 offset/limit 分页前执行;排序 updated_at DESC, id DESC(稳定次序)。
    cursor 条件哈希纳入全部筛选维度(status 列表排序后入哈希),跨条件复用游标
    → invalid_request。
    """
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    statuses = _normalize_statuses(status)
    days = _normalize_updated_within_days(updated_within_days)
    keyword = _normalize_keyword(keyword)
    filters = {
        "project_id": str(project_id),
        "requirement_id": requirement_id,
        "assignee_id": str(assignee_id) if assignee_id else None,
        "statuses": statuses,
        "updated_within_days": days,
        "keyword": keyword,
    }
    from .pagination import decode_cursor

    offset = decode_cursor(filters, cursor)
    stmt = select(Task, func.substr(Task.description, 1, 240),
                  func.length(Task.description) > 240).options(defer(Task.description)).where(Task.project_id == project_id, Task.deleted_at.is_(None), Task.has_active_requirement())
    if requirement_id:
        from .short_codes import require_valid_code

        require_valid_code("requirement", requirement_id)
        stmt = stmt.where(Task.requirement_id == requirement_id)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if statuses:
        stmt = stmt.where(Task.status.in_(statuses))
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where(Task.updated_at >= cutoff)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Task.title.ilike(like), Task.description.ilike(like)))
    rows = db.execute(
        stmt.order_by(Task.updated_at.desc(), Task.code.desc()).offset(offset).limit(limit)
    ).all()
    items = [_task_dict(db, t, excerpt=(body, bool(truncated))) for t, body, truncated in rows]
    return page_result(items, offset, limit, filters)


def update_task(
    db: Session,
    actor: User,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    project_id: uuid.UUID | None = None,
    expected_version: int | None = None,
) -> Task:
    """更新需求内任务；任务的归属不可变。"""
    task = _get_editable(db, actor, task_id, project_id)
    if title is not None or description is not None:
        work_content.revise(db, actor, task, title, description, expected_version)
    db.commit()
    return task


def set_task_status(
    db: Session, actor: User, task_id: str, target: str, project_id: uuid.UUID | None = None
) -> Task:
    """通用改状态:任意目标态自由流转,无任何前置校验;已指派任务走所有权守卫。"""
    task = _get_editable(db, actor, task_id, project_id)
    task = db.scalar(
        select(Task)
        .where(Task.project_id == task.project_id, Task.code == task.code, Task.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise not_found("任务不存在")
    _require_owner(db, actor, task)
    assert_status_valid(task.status, target, "任务")
    old = task.status
    task.status = target
    record_activity(
        db,
        task.project_id,
        actor.id,
        "task",
        task.code,
        "status",
        f"{STATUS_CN[old]} → {STATUS_CN[target]}",
    )
    record_system_event(
        db, actor.id, ResourceRef(task.project_id, ResourceKind.REQUIREMENT, task.requirement_id),
        event_type="task.status_changed", event_data={"before": old, "after": target},
        source_task=task.code,
    )
    db.commit()
    return task


def assign_task(
    db: Session, actor: User, task_id: str, assignee_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> Task:
    """未指派任务任何编辑权者可指派;已指派仅本人/管理员可改派。"""
    task = _get_editable(db, actor, task_id, project_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法改派")
    if task.assignee_id is not None:
        _require_owner(db, actor, task)
    assignee = _check_assignee(db, task.project_id, assignee_id)
    remember_assignees(db, task, task.assignee_id, assignee_id)
    task.assignee_id = assignee_id
    record_activity(
        db, task.project_id, actor.id, "task", task.code, "assign", f"指派给 {display_name(assignee)}"
    )
    db.commit()
    return task


def claim_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    """未指派任务的认领;条件 UPDATE 原子化,并发竞争败者得 conflict。"""
    task = _get_editable(db, actor, task_id, project_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法认领")
    try:
        requirement_code = db.execute(
            update(Task)
            .where(
                Task.project_id == task.project_id,
                Task.code == task.code,
                Task.assignee_id.is_(None),
                Task.deleted_at.is_(None),
                Task.status.not_in(TERMINAL),
            )
            .values(assignee_id=actor.id)
            .returning(Task.requirement_id)
        ).scalar_one_or_none()
    except OperationalError:
        db.rollback()
        raise conflict("并发认领冲突,请重试")
    if requirement_code is None:
        db.rollback()
        raise conflict("任务已被认领")
    db.flush()
    record_activity(db, task.project_id, actor.id, "task", task.code, "claim", "认领任务")
    record_system_event(
        db, actor.id, ResourceRef(task.project_id, ResourceKind.REQUIREMENT, requirement_code),
        event_type="task.claimed", event_data={"before": None, "after": str(actor.id)},
        source_task=task.code,
    )
    db.commit()
    return task


def unassign_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    task = _get_editable(db, actor, task_id, project_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法解除指派")
    _require_owner(db, actor, task)
    remember_assignees(db, task, task.assignee_id)
    task.assignee_id = None
    record_activity(db, task.project_id, actor.id, "task", task.code, "unassign", "解除指派")
    db.commit()
    return task


def cancel_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    """取消任务:set_task_status("cancelled") 便捷封装。"""
    return set_task_status(db, actor, task_id, "cancelled", project_id=project_id)


def delete_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> None:
    task = _get_editable(db, actor, task_id, project_id)
    _require_owner(db, actor, task)
    task.deleted_at = _now()
    task.deleted_by = actor.id
    record_activity(db, task.project_id, actor.id, "task", task.code, "delete", "删除任务")
    db.commit()


def restore_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    from .work_trash import find_deleted

    task = find_deleted(db, actor, "task", task_id, project_id)
    requirement = db.get(Requirement, (task.project_id, task.requirement_id))
    if requirement is None or requirement.deleted_at is not None:
        raise conflict("所属需求尚未恢复，请先恢复需求")
    task.deleted_at = None
    task.deleted_by = None
    record_activity(db, task.project_id, actor.id, "task", task.code, "restore", "恢复任务")
    db.commit()
    return task


def _normalize_statuses(status: str | list[str] | None) -> list[str] | None:
    """status 多值归一化:str → [str];list 保序去空;None/空 → None(不过滤)。"""
    if status is None:
        return None
    if isinstance(status, str):
        statuses = [status]
    else:
        statuses = list(status)
    cleaned = [s.strip() for s in statuses if isinstance(s, str) and s.strip()]
    cleaned.sort()  # 条件哈希稳定:同条件顺序互换复用游标
    return cleaned or None


def _normalize_updated_within_days(value: int | str | None) -> int | None:
    """updated_within_days 校验:None → None;整数/数字字符串 ≥1 → int;其余 → invalid_request。"""
    if value is None:
        return None
    if isinstance(value, bool):
        raise invalid_request("updated_within_days 必须是 ≥1 的整数")
    if isinstance(value, int):
        days = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            raise invalid_request("updated_within_days 必须是 ≥1 的整数")
        days = int(text)
    else:
        raise invalid_request("updated_within_days 必须是 ≥1 的整数")
    if days < 1:
        raise invalid_request("updated_within_days 必须是 ≥1 的整数")
    return days


def _normalize_keyword(keyword: str | None) -> str | None:
    """keyword:strip,空 → None(不过滤)。"""
    if keyword is None:
        return None
    text = str(keyword).strip()
    return text or None


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
