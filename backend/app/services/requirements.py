"""需求服务:CRUD + 五态状态机操作(规格书 §3.1)。

- 通用改状态 set_requirement_status(任意目标态,无前置校验);cancel 为便捷封装
- 状态完全手动:任务状态变化不影响需求状态(自动流转已删除),需求状态仅由操作者显式控制
- 验收说明机制删除:activity 只记 status action + 旧态 → 新态摘要
- 删除 = 软删 + 任务数二次确认(规格书 §4.2);恢复 = 撤销软删
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Requirement, Task, User
from .labels import STATUS_CN
from .pagination import page_result
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity
from .short_text import normalize_short_description
from .workflow import assert_status_valid


def _requirement_dict(db: Session, r: Requirement) -> dict:
    return {
        "id": str(r.id),
        "title": r.title,
        "description": r.description,
        "status": r.status,
        "project_id": str(r.project_id),
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "task_count": db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.requirement_id == r.id, Task.deleted_at.is_(None))
        ),
        "done_task_count": db.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.requirement_id == r.id,
                Task.deleted_at.is_(None),
                Task.status == "done",
            )
        ),
    }


def create_requirement(
    db: Session, actor: User, project_id: uuid.UUID, title: str, description: str | None = None
) -> Requirement:
    title = title.strip()
    if not title:
        raise invalid_request("标题不能为空")
    require_project_role(db, actor.id, project_id, min_level="editor")
    description = normalize_short_description(description)
    requirement = Requirement(
        project_id=project_id, title=title, description=description, created_by=actor.id
    )
    db.add(requirement)
    db.flush()
    record_activity(db, project_id, actor.id, "requirement", requirement.id, "create", "创建需求")
    db.commit()
    return requirement


def get_requirement(db: Session, user: User, requirement_id: uuid.UUID) -> Requirement:
    requirement = db.scalar(
        select(Requirement).where(
            Requirement.id == requirement_id, Requirement.deleted_at.is_(None)
        )
    )
    if requirement is None:
        raise not_found("需求不存在")
    get_accessible_project(db, user.id, requirement.project_id, min_level="viewer")
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
) -> dict:
    """需求列表:多值状态 / updated_within_days 时间窗口 / keyword 标题或描述包含。

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
        "statuses": statuses,
        "updated_within_days": days,
        "keyword": keyword,
    }
    from .pagination import decode_cursor

    offset = decode_cursor(filters, cursor)
    stmt = select(Requirement).where(
        Requirement.project_id == project_id, Requirement.deleted_at.is_(None)
    )
    if statuses:
        stmt = stmt.where(Requirement.status.in_(statuses))
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = stmt.where(Requirement.updated_at >= cutoff)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(Requirement.title.ilike(like), Requirement.description.ilike(like))
        )
    rows = db.scalars(
        stmt.order_by(Requirement.updated_at.desc(), Requirement.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_requirement_dict(db, r) for r in rows]
    return page_result(items, offset, limit, filters)


def update_requirement(
    db: Session,
    actor: User,
    requirement_id: uuid.UUID,
    title: str | None,
    description: str | None,
) -> Requirement:
    requirement = _get_editable(db, actor, requirement_id)
    if title is not None:
        title = title.strip()
        if not title:
            raise invalid_request("标题不能为空")
        requirement.title = title
    if description is not None:
        requirement.description = normalize_short_description(description)
    record_activity(db, requirement.project_id, actor.id, "requirement", requirement.id, "update", "更新需求")
    db.commit()
    return requirement


def set_requirement_status(
    db: Session, actor: User, requirement_id: uuid.UUID, target: str
) -> Requirement:
    """通用改状态:任意目标态自由流转,无任何前置校验(含 pending 确认)。"""
    requirement = _get_editable(db, actor, requirement_id)
    assert_status_valid(requirement.status, target, "需求")
    old = requirement.status
    requirement.status = target
    record_activity(
        db,
        requirement.project_id,
        actor.id,
        "requirement",
        requirement.id,
        "status",
        f"{STATUS_CN[old]} → {STATUS_CN[target]}",
    )
    db.commit()
    return requirement


def cancel_requirement(db: Session, actor: User, requirement_id: uuid.UUID) -> Requirement:
    """取消需求:set_status("cancelled") 便捷封装。"""
    return set_requirement_status(db, actor, requirement_id, "cancelled")


def delete_requirement(
    db: Session, actor: User, requirement_id: uuid.UUID, confirm_task_count: int | None = None
) -> None:
    """软删;需求下有任务时需确认任务数(二次确认,规格书 §4.2)。"""
    requirement = _get_editable(db, actor, requirement_id)
    task_count = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.requirement_id == requirement.id, Task.deleted_at.is_(None))
    )
    if task_count > 0 and confirm_task_count != task_count:
        raise conflict(f"需求下有 {task_count} 个任务,请确认任务数后删除")
    requirement.deleted_at = _now()
    from .attachments import soft_delete_for_target

    soft_delete_for_target(db, requirement.project_id, "requirement", requirement.id)
    record_activity(db, requirement.project_id, actor.id, "requirement", requirement.id, "delete", "删除需求")
    db.commit()


def restore_requirement(db: Session, actor: User, requirement_id: uuid.UUID) -> Requirement:
    requirement = db.scalar(select(Requirement).where(Requirement.id == requirement_id))
    if requirement is None or requirement.deleted_at is None:
        raise not_found("已删除的需求不存在")
    require_project_role(db, actor.id, requirement.project_id, min_level="editor")
    requirement.deleted_at = None
    record_activity(db, requirement.project_id, actor.id, "requirement", requirement.id, "restore", "恢复需求")
    db.commit()
    return requirement


def _get_editable(db: Session, actor: User, requirement_id: uuid.UUID) -> Requirement:
    requirement = db.scalar(
        select(Requirement).where(
            Requirement.id == requirement_id, Requirement.deleted_at.is_(None)
        )
    )
    if requirement is None:
        raise not_found("需求不存在")
    require_project_role(db, actor.id, requirement.project_id, min_level="editor")
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


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
