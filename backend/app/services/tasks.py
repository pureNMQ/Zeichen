"""任务服务:CRUD + 四态状态机 + 指派/认领/改派(§3.2/§5.1;ADR 0003 收归需求;ADR 0002 短码寻址)。

任务必须挂同项目已确认需求(requirement_id 存 REQ-n 短码);可改指向、禁止置空。
主键 = (project_id, code);对外 id 一律 TASK-n;无项目上下文读取按可访问项目消歧。
所有权规则(已指派任务):仅被指派者本人 / 工作区 admin / 项目 owner 可改状态/改派;
未指派任务任何编辑权者可操作。状态流转走通用 set_task_status(任意目标态自由流转,
无前置校验);任务状态变化不影响需求状态(自动流转已删除,需求状态全手动)。
认领用条件 UPDATE 原子化,并发竞争败者得 conflict。
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Requirement, Task, User
from . import task_blockers
from .labels import STATUS_CN
from .pagination import page_result
from .permissions import get_accessible_project, get_project_role, is_admin, require_project_role
from .polymorphic import record_activity
from .short_text import normalize_short_description
from .user_profiles import avatar_url, display_name
from .workflow import TERMINAL, assert_status_valid

# update_task 的 requirement_id / blocked_by 哨兵:未传 = 不变;None/[] = 显式解除/清空
_UNSET = object()


def _task_dict(db: Session, t: Task) -> dict:
    assignee = db.get(User, t.assignee_id) if t.assignee_id else None
    blocked_by = task_blockers.blocker_summaries(db, t)
    return {
        "id": t.code,
        "title": t.title,
        "description": t.description,
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
        "blocked": task_blockers.is_blocked([i["status"] for i in blocked_by]),
        "blocked_by": blocked_by,
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
    """需求须存在(REQ-n)、已确认、未删除、且与任务同项目(跨项目拒绝)。"""
    from .requirements import get_requirement_in_project
    from .short_codes import require_valid_code

    require_valid_code("requirement", requirement_id)
    requirement = get_requirement_in_project(db, project_id, requirement_id)
    if requirement.project_id != project_id:  # pragma: no cover - 项目内查询已约束
        raise invalid_request("任务所属项目与需求不一致")
    if requirement.status == "pending":
        raise invalid_request("待确认需求不能创建或关联任务,请先确认需求")


def create_task(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    title: str,
    description: str | None = None,
    requirement_id: str | None = None,
    assignee_id: uuid.UUID | None = None,
    blocked_by: list[str] | None = None,
) -> Task:
    """创建任务:必须挂同项目已确认需求(REQ-n 短码;ADR 0003,无独立任务)。"""
    from .short_codes import allocate_code

    title = title.strip()
    if not title:
        raise invalid_request("标题不能为空")
    if requirement_id is None:
        raise invalid_request("任务必须挂需求,请指定 requirement_id")
    require_project_role(db, actor.id, project_id, min_level="editor")
    description = normalize_short_description(description)
    _check_requirement(db, project_id, requirement_id)
    if assignee_id is not None:
        _check_assignee(db, project_id, assignee_id)
    code = allocate_code(db, project_id, "task")
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
    if blocked_by:
        task_blockers.set_blockers_core(db, actor, task, blocked_by)
    record_activity(db, project_id, actor.id, "task", code, "create", "创建任务")
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
    stmt = select(Task).where(Task.project_id == project_id, Task.deleted_at.is_(None))
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
    rows = db.scalars(
        stmt.order_by(Task.updated_at.desc(), Task.code.desc()).offset(offset).limit(limit)
    ).all()
    items = [_task_dict(db, t) for t in rows]
    return page_result(items, offset, limit, filters)


def update_task(
    db: Session,
    actor: User,
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    requirement_id: object = _UNSET,
    blocked_by: object = _UNSET,
    project_id: uuid.UUID | None = None,
) -> Task:
    """更新任务元数据;requirement_id 可换同项目其他需求但不可置空;blocked_by 可整体替换/清空。

    requirement_id 权限与改状态同规则(已指派仅本人/工作区 admin/项目 owner,
    未指派任意编辑权);校验需求同项目且未删除。blocked_by 整体替换前置集合。
    """
    task = _get_editable(db, actor, task_id, project_id)
    if title is not None:
        title = title.strip()
        if not title:
            raise invalid_request("标题不能为空")
        task.title = title
    if description is not None:
        task.description = normalize_short_description(description)
    summary = "更新任务"
    if requirement_id is not _UNSET:
        _require_owner(db, actor, task)
        if requirement_id is None:
            raise invalid_request("任务必须挂需求,不能解除关联")
        rid = str(requirement_id)
        if rid != task.requirement_id:
            _check_requirement(db, task.project_id, rid)
            task.requirement_id = rid
            summary = "关联需求"
    if blocked_by is not _UNSET:
        task_blockers.set_blockers_core(db, actor, task, blocked_by)
    record_activity(db, task.project_id, actor.id, "task", task.code, "update", summary)
    db.commit()
    return task


def set_task_status(
    db: Session, actor: User, task_id: str, target: str, project_id: uuid.UUID | None = None
) -> Task:
    """通用改状态:任意目标态自由流转,无任何前置校验;已指派任务走所有权守卫。"""
    task = _get_editable(db, actor, task_id, project_id)
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
        result = db.execute(
            update(Task)
            .where(
                Task.project_id == task.project_id,
                Task.code == task.code,
                Task.assignee_id.is_(None),
            )
            .values(assignee_id=actor.id)
        )
    except OperationalError:
        db.rollback()
        raise conflict("并发认领冲突,请重试")
    if result.rowcount != 1:
        db.rollback()
        raise conflict("任务已被认领")
    db.flush()
    record_activity(db, task.project_id, actor.id, "task", task.code, "claim", "认领任务")
    db.commit()
    return task


def unassign_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    task = _get_editable(db, actor, task_id, project_id)
    if task.status in TERMINAL:
        raise conflict("任务已结束,无法解除指派")
    _require_owner(db, actor, task)
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
    from .attachments import soft_delete_for_target

    soft_delete_for_target(db, task.project_id, "task", task.code)
    record_activity(db, task.project_id, actor.id, "task", task.code, "delete", "删除任务")
    db.commit()


def restore_task(
    db: Session, actor: User, task_id: str, project_id: uuid.UUID | None = None
) -> Task:
    from .short_codes import require_valid_code

    require_valid_code("task", task_id)
    stmt = select(Task).where(Task.code == task_id)
    if project_id is not None:
        get_accessible_project(db, actor.id, project_id, min_level="viewer")
        stmt = stmt.where(Task.project_id == project_id)
    rows = db.scalars(stmt).all()
    task = next((t for t in rows if t.deleted_at is not None), None)
    if task is None:
        raise not_found("已删除的任务不存在")
    require_project_role(db, actor.id, task.project_id, min_level="editor")
    task.deleted_at = None
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
