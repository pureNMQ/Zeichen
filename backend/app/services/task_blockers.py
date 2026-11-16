"""任务阻塞依赖(REQ-7):同项目任务间的协作性前置关系(ADR 0002:task_id/blocker_id 存 TASK-n 短码)。

阻塞只是协作信息:不改变任务自由状态机,不自动阻止认领/实施;
仅「已完成」解除阻塞(其余状态含 cancelled 均视为受阻);
软删前置 = 依赖自动失效(不计入 blocked、不出现在摘要),恢复后阻塞立即恢复。
规则:仅同项目;禁自依赖;重复依赖与循环依赖 → conflict;边行不软删,移除 = 物理删行。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Task, TaskBlocker, User
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity

# update_task 的 blocked_by 哨兵复用 tasks._UNSET 语义:未传 = 不变;[] = 清空


def is_blocked(prerequisite_statuses: list[str]) -> bool:
    """任一前置状态非 done → 受阻;空集合 → 未受阻(纯函数)。"""
    return any(status != "done" for status in prerequisite_statuses)


def blocker_summaries(db: Session, task: Task) -> list[dict]:
    """前置摘要(列表/详情字典共用):软删前置自动失效,按创建时间稳定排序。

    id 即任务短码(TASK-n)。
    """
    rows = db.execute(
        select(TaskBlocker, Task)
        .join(
            Task,
            (Task.project_id == TaskBlocker.project_id)
            & (Task.code == TaskBlocker.blocker_id),
        )
        .where(
            TaskBlocker.project_id == task.project_id,
            TaskBlocker.task_id == task.code,
            Task.deleted_at.is_(None),
        )
        .order_by(TaskBlocker.created_at, TaskBlocker.task_id, TaskBlocker.blocker_id)
    ).all()
    return [
        {
            "id": blocker.code,
            "title": blocker.title,
            "status": blocker.status,
            "resolved": blocker.status == "done",
        }
        for _, blocker in rows
    ]


def list_blockers(db: Session, user: User, task_id: str) -> dict:
    """查询阻塞状态:viewer 可读;blocked 与摘要一并返回。"""
    task = _load_task(db, user, task_id, editable=False)
    items = blocker_summaries(db, task)
    return {"blocked": is_blocked([item["status"] for item in items]), "items": items}


def add_blocker(db: Session, actor: User, task_id: str, blocker_id: str) -> TaskBlocker:
    """创建单条依赖;editor+ 可维护,viewer 拒绝。"""
    task = _load_task(db, actor, task_id, editable=True)
    _ensure_no_self(task, blocker_id)
    blocker = _load_blocker(db, task, blocker_id)
    _ensure_no_duplicate(db, task, blocker_id)
    _ensure_no_cycle(db, task.project_id, task.code, {blocker_id})
    edge = TaskBlocker(
        task_id=task.code,
        blocker_id=blocker.code,
        project_id=task.project_id,
        created_by=actor.id,
    )
    db.add(edge)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise conflict("前置任务依赖已存在")
    record_activity(
        db, task.project_id, actor.id, "task", task.code, "blocker",
        f"增加前置任务 {blocker.title}",
    )
    db.commit()
    return edge


def set_blockers(db: Session, actor: User, task_id: str, blocker_ids: list[str] | None) -> Task:
    """整体替换前置集合(编辑语义);规则校验通过后差量落库。"""
    task = _load_task(db, actor, task_id, editable=True)
    set_blockers_core(db, actor, task, blocker_ids)
    db.commit()
    return task


def remove_blocker(
    db: Session, actor: User, task_id: str, blocker_id: str,
    project_id: uuid.UUID | None = None,
) -> None:
    task = _load_task(db, actor, task_id, editable=True, project_id=project_id)
    edge = db.scalar(
        select(TaskBlocker).where(
            TaskBlocker.project_id == task.project_id,
            TaskBlocker.task_id == task.code,
            TaskBlocker.blocker_id == blocker_id,
        )
    )
    if edge is None:
        raise not_found("前置任务依赖不存在")
    blocker = db.scalar(
        select(Task).where(
            Task.project_id == task.project_id, Task.code == blocker_id
        )
    )
    db.delete(edge)
    db.flush()
    title = blocker.title if blocker else blocker_id
    record_activity(
        db, task.project_id, actor.id, "task", task.code, "blocker",
        f"移除前置任务 {title}",
    )
    db.commit()


def set_blockers_core(db: Session, actor: User, task: Task, blocker_ids: list[str] | None) -> None:
    """校验并差量写入前置集合(不 commit,供 tasks.create/update 复用)。短码入参。"""
    from .short_codes import require_valid_code

    ids = [str(x) for x in (blocker_ids or [])]
    for bid in ids:
        require_valid_code("task", bid)
    if len(set(ids)) != len(ids):
        raise conflict("前置任务重复")
    for bid in ids:
        _ensure_no_self(task, bid)
        _load_blocker(db, task, bid)
    _ensure_no_cycle(db, task.project_id, task.code, set(ids))
    existing = db.scalars(
        select(TaskBlocker).where(
            TaskBlocker.project_id == task.project_id, TaskBlocker.task_id == task.code
        )
    ).all()
    keep = set(ids)
    for edge in existing:
        if edge.blocker_id not in keep:
            db.delete(edge)
    existing_ids = {edge.blocker_id for edge in existing}
    for bid in ids:
        if bid not in existing_ids:
            db.add(
                TaskBlocker(
                    task_id=task.code,
                    blocker_id=bid,
                    project_id=task.project_id,
                    created_by=actor.id,
                )
            )
    db.flush()
    summary = "清空前置任务" if not ids else f"设置前置任务({len(ids)}项)"
    record_activity(db, task.project_id, actor.id, "task", task.code, "blocker", summary)


def _load_task(
    db: Session, user: User, task_id: str, *, editable: bool,
    project_id: uuid.UUID | None = None,
) -> Task:
    """目标任务加载:短码寻址 + 未删 + 可见(viewer)/可编辑(editor+)。"""
    from .short_code_lookup import resolve_by_code
    from .short_codes import require_valid_code

    require_valid_code("task", task_id)
    task, _project = resolve_by_code(db, user, "task", task_id, project_id=project_id)
    if task is None:
        raise not_found("任务不存在")
    if editable:
        require_project_role(db, user.id, task.project_id, min_level="editor")
    else:
        get_accessible_project(db, user.id, task.project_id, min_level="viewer")
    return task


def _ensure_no_self(task: Task, blocker_id: str) -> None:
    if blocker_id == task.code:
        raise invalid_request("任务不能以自身为前置任务")


def _load_blocker(db: Session, task: Task, blocker_id: str) -> Task:
    """前置任务必须存在(同项目短码)、未删除。"""
    from .short_codes import require_valid_code

    require_valid_code("task", blocker_id)
    blocker = db.scalar(
        select(Task).where(
            Task.project_id == task.project_id,
            Task.code == blocker_id,
            Task.deleted_at.is_(None),
        )
    )
    if blocker is None:
        raise not_found("前置任务不存在")
    if blocker.project_id != task.project_id:
        raise invalid_request("前置任务与目标任务不在同一项目")
    return blocker


def _ensure_no_duplicate(db: Session, task: Task, blocker_id: str) -> None:
    dup = db.scalar(
        select(TaskBlocker.task_id).where(
            TaskBlocker.project_id == task.project_id,
            TaskBlocker.task_id == task.code,
            TaskBlocker.blocker_id == blocker_id,
        )
    )
    if dup is not None:
        raise conflict("前置任务依赖已存在")


def _ensure_no_cycle(
    db: Session, project_id: uuid.UUID, task_id: str, new_blocker_ids: set[str]
) -> None:
    """循环检测:项目内全部依赖边 + 待建边,从 task 沿「被阻塞 → 前置」方向可达自身即冲突。"""
    rows = db.execute(
        select(TaskBlocker.task_id, TaskBlocker.blocker_id).where(
            TaskBlocker.project_id == project_id
        )
    ).all()
    adjacency: dict[str, set[str]] = {}
    for src, dst in rows:
        adjacency.setdefault(src, set()).add(dst)
    # set 语义:替换 task 的既有出边;add 语义:增量并入(既有出边不可能成环,不会误报)
    adjacency.setdefault(task_id, set()).update(new_blocker_ids)
    visited = {task_id}
    stack = [task_id]
    while stack:
        current = stack.pop()
        for nxt in adjacency.get(current, ()):
            if nxt == task_id:
                raise conflict("存在循环依赖")
            if nxt not in visited:
                visited.add(nxt)
                stack.append(nxt)
