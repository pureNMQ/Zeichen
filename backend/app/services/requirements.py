"""需求服务:CRUD + 六态状态机操作(ADR 0002 短码寻址 / ADR 0003 验收上移需求)。

- 通用改状态 set_requirement_status(任意目标态,无前置校验);cancel 为便捷封装
- 主键 = (project_id, code);对外 id 一律短码 REQ-n
- 短码仅项目内唯一:无项目上下文的读取按用户可访问项目消歧(多命中 → invalid_request)
- 删除 = 软删 + 任务数二次确认;恢复 = 撤销软删(短码不变)
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, defer

from ..errors import conflict, invalid_request, not_found
from ..models import Requirement, Task, User
from ..v2.commands import execute_once
from ..v2.resource_refs import ResourceKind, ResourceRef
from ..v2.timeline import record_manual_entry, record_system_event
from .labels import STATUS_CN
from .pagination import page_result
from .requirement_board import board_details, my_requirements, recent_activity
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity
from .short_code_lookup import resolve_by_code
from .short_codes import require_valid_code
from ..v2 import work_content
from .workflow import assert_status_valid


def _requirement_dict(db: Session, r: Requirement, board=None, *, excerpt: tuple[str | None, bool] | None = None) -> dict:
    return {
        **(board if board is not None else board_details(db, r.project_id, [r.code])[r.code]),
        "id": r.code,
        "project_id": str(r.project_id),
        "title": r.title,
        "description": excerpt[0] if excerpt else r.description,
        **({"description_truncated": excerpt[1]} if excerpt else {}),
        "version": r.version,
        "status": r.status,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
    }


def create_requirement(
    db: Session, actor: User, project_id: uuid.UUID, title: str, description: str | None = None,
    *, commit: bool = True,
) -> Requirement:
    from .short_codes import allocate_code

    title = work_content.document_title(title)
    require_project_role(db, actor.id, project_id, min_level="editor")
    description = work_content.markdown(description)
    code = allocate_code(db, project_id, "requirement")
    requirement = Requirement(
        project_id=project_id, code=code, title=title, description=description, created_by=actor.id
    )
    db.add(requirement)
    db.flush()
    work_content.snapshot(db, requirement, actor.id)
    work_content.notify_body_mentions(db, requirement, actor.id)
    record_activity(db, project_id, actor.id, "requirement", code, "create", "创建需求")
    if commit:
        db.commit()
    return requirement


def get_requirement_in_project(db: Session, project_id: uuid.UUID, code: str) -> Requirement:
    """项目内按短码取未删除需求;格式非法 → invalid_request,未命中 → not_found。"""
    require_valid_code("requirement", code)
    requirement = db.scalar(
        select(Requirement).where(Requirement.project_id == project_id, Requirement.code == code)
    )
    if requirement is None or requirement.deleted_at is not None:
        raise not_found("需求不存在")
    return requirement


def get_requirement(
    db: Session, user: User, requirement_id: str, project_id: uuid.UUID | None = None
) -> Requirement:
    requirement, _project = resolve_by_code(db, user, "requirement", requirement_id, project_id=project_id)
    return requirement


def list_requirements(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    status: str | list[str] | None,
    cursor: str | None,
    limit: int,
    updated_within_days: int | str | None = None,
    keyword: str | None = None,
    participated_by_me: bool = False,
) -> dict:
    """需求列表:多值状态 / updated_within_days 时间窗口 / keyword 标题或描述包含。

    按需求、子任务和时间轴的最近活动时间筛选并倒序分页；相同时间按短码倒序。
    """
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    statuses = _normalize_statuses(status)
    days = _normalize_updated_within_days(updated_within_days)
    keyword = _normalize_keyword(keyword)
    filters = {
        "project_id": str(project_id),
        "statuses": statuses,
        "updated_within_days": days,
        "keyword": keyword,
    }
    from .pagination import decode_cursor
    if participated_by_me:
        filters["participant"] = str(user.owner_id or user.id)

    offset = decode_cursor(filters, cursor)
    activity = recent_activity(project_id)
    last_activity = activity.c.last_activity_at
    stmt = select(Requirement, func.substr(Requirement.description, 1, 240),
                  func.length(Requirement.description) > 240, last_activity).join(
        activity, activity.c.code == Requirement.code
    ).options(defer(Requirement.description)).where(
        Requirement.project_id == project_id, Requirement.deleted_at.is_(None)
    )
    if statuses:
        stmt = stmt.where(Requirement.status.in_(statuses))
    if participated_by_me:
        stmt = stmt.where(Requirement.code.in_(my_requirements(project_id, user)))
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where(last_activity >= cutoff)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(Requirement.title.ilike(like), Requirement.description.ilike(like), Requirement.code.ilike(like))
        )
    rows = db.execute(
        stmt.order_by(last_activity.desc(), Requirement.code.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    details = board_details(db, project_id, [r.code for r, _, _, _ in rows])
    items = [
        {**_requirement_dict(db, r, details[r.code], excerpt=(body, bool(truncated))),
         "last_activity_at": active_at.isoformat()}
        for r, body, truncated, active_at in rows
    ]
    return page_result(items, offset, limit, filters)


def update_requirement(
    db: Session,
    actor: User,
    requirement_id: str,
    title: str | None = None,
    description: str | None = None,
    project_id: uuid.UUID | None = None,
    expected_version: int | None = None,
) -> Requirement:
    requirement = get_requirement(db, actor, requirement_id, project_id)
    require_project_role(db, actor.id, requirement.project_id, min_level="editor")
    if title is not None or description is not None:
        work_content.revise(db, actor, requirement, title, description, expected_version)
    db.commit()
    return requirement


def _lock_requirement(db: Session, project_id: uuid.UUID, code: str) -> Requirement:
    requirement = db.scalar(
        select(Requirement)
        .where(Requirement.project_id == project_id, Requirement.code == code,
               Requirement.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if requirement is None:
        raise not_found("需求不存在")
    return requirement


def _change_status(db: Session, actor: User, requirement: Requirement, target: str) -> None:
    assert_status_valid(requirement.status, target, "需求")
    old = requirement.status
    requirement.status = target
    record_activity(
        db,
        requirement.project_id,
        actor.id,
        "requirement",
        requirement.code,
        "status",
        f"{STATUS_CN[old]} → {STATUS_CN[target]}",
    )
    record_system_event(
        db, actor.id, ResourceRef(requirement.project_id, ResourceKind.REQUIREMENT, requirement.code),
        event_type="requirement.status_changed", event_data={"before": old, "after": target},
    )


def set_requirement_status(
    db: Session, actor: User, requirement_id: str, target: str,
    project_id: uuid.UUID | None = None,
) -> Requirement:
    """通用改状态:任意目标态自由流转,无任何前置校验(同态 conflict)。"""
    requirement = get_requirement(db, actor, requirement_id, project_id)
    require_project_role(db, actor.id, requirement.project_id, min_level="editor")
    requirement = _lock_requirement(db, requirement.project_id, requirement.code)
    _change_status(db, actor, requirement, target)
    db.commit()
    return requirement


def reject_requirement(
    db: Session, actor: User, project_id: uuid.UUID, requirement_id: str, reason: str, request_id: uuid.UUID,
) -> dict:
    """将验收中的需求退回待办，并在同一事务内记录打回理由。由调用方提交。"""
    scope = ResourceRef(project_id, ResourceKind.REQUIREMENT, requirement_id)
    require_project_role(db, actor.id, project_id, min_level="editor")
    get_requirement_in_project(db, project_id, requirement_id)
    reason = reason.strip().replace("\r\n", "\n").replace("\r", "\n")
    if not reason or len(reason) > 2000 or "\x00" in reason:
        raise invalid_request("打回理由须包含 1 至 2000 个有效字符")

    def apply() -> dict:
        requirement = _lock_requirement(db, project_id, requirement_id)
        if requirement.status != "verifying":
            raise conflict("仅可打回验收中的需求，请刷新需求状态")
        _change_status(db, actor, requirement, "backlog")
        return record_manual_entry(db, actor, scope, body=f"打回：{reason}")

    return execute_once(
        db, project_id=project_id, actor_id=actor.id, operation="requirement.reject", request_id=request_id,
        payload={"requirement": requirement_id, "reason": reason}, apply=apply,
    )


def cancel_requirement(
    db: Session, actor: User, requirement_id: str, project_id: uuid.UUID | None = None
) -> Requirement:
    """取消需求:set_status("cancelled") 便捷封装。"""
    return set_requirement_status(db, actor, requirement_id, "cancelled", project_id=project_id)


def delete_requirement(
    db: Session, actor: User, requirement_id: str, confirm_task_count: int | None = None,
    project_id: uuid.UUID | None = None,
) -> None:
    """软删;需求下有任务时需确认任务数(二次确认,规格书 §4.2)。"""
    requirement = get_requirement(db, actor, requirement_id, project_id)
    require_project_role(db, actor.id, requirement.project_id, min_level="editor")
    task_count = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(
            Task.requirement_id == requirement.code,
            Task.project_id == requirement.project_id,
            Task.deleted_at.is_(None),
        )
    )
    if task_count > 0 and confirm_task_count != task_count:
        raise conflict(f"需求下有 {task_count} 个任务,请确认任务数后删除")
    requirement.deleted_at = datetime.now(timezone.utc)
    requirement.deleted_by = actor.id
    record_activity(
        db, requirement.project_id, actor.id, "requirement", requirement.code, "delete", "删除需求"
    )
    db.commit()


def restore_requirement(
    db: Session, actor: User, requirement_id: str, project_id: uuid.UUID | None = None
) -> Requirement:
    from .work_trash import find_deleted

    requirement = find_deleted(db, actor, "requirement", requirement_id, project_id)
    requirement.deleted_at = None
    requirement.deleted_by = None
    record_activity(
        db, requirement.project_id, actor.id, "requirement", requirement.code, "restore", "恢复需求"
    )
    db.commit()
    return requirement


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
