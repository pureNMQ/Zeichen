"""个人筛选视图服务:CRUD + criteria 白名单校验。

契约(任务 T2):
- 校验在 service 层抛 invalid_request(错误四件套 code: message 前缀)
- 权限:项目访问统一 get_accessible_project(min_level="viewer")——非成员 404 not_found,
  viewer 及以上可创建自己的视图(个人偏好,不要求 editor)
- 视图归属:查询一律按 (id, user_id) 过滤;非本人视图 → not_found(404),含 PATCH/DELETE
- 同名(project_id, user_id, entity_type, name)重复创建 → conflict(先查重,IntegrityError 兜底)
- 删除为物理删除(db.delete + commit);空 criteria 允许(={})
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import ProjectFilterView, User
from .permissions import get_accessible_project
from .workflow import REQUIREMENT_STATUSES, TASK_STATUSES

ENTITY_TYPES = ("requirement", "task")
VIEW_MODES = ("board", "list")
CRITERIA_KEYS = ("statuses", "updated_within_days", "keyword", "assignee_id", "view_mode")
_STATUSES_BY_ENTITY = {
    "requirement": frozenset(REQUIREMENT_STATUSES),
    "task": frozenset(TASK_STATUSES),
}


def _view_dict(view: ProjectFilterView) -> dict:
    return {
        "id": str(view.id),
        "project_id": str(view.project_id),
        "user_id": str(view.user_id),
        "entity_type": view.entity_type,
        "name": view.name,
        "criteria": view.criteria,
        "created_at": view.created_at.isoformat(),
        "updated_at": view.updated_at.isoformat(),
    }


def _validate_entity_type(entity_type: str | None) -> str:
    if entity_type not in ENTITY_TYPES:
        raise invalid_request(f"非法的实体类型: {entity_type}")
    return entity_type


def _validate_name(name: str | None) -> str:
    if not isinstance(name, str):
        raise invalid_request("名称不能为空")
    name = name.strip()
    if not name:
        raise invalid_request("名称不能为空")
    if len(name) > 50:
        raise invalid_request("名称不能超过 50 字符")
    return name


def _validate_criteria(entity_type: str, criteria: dict | None) -> dict:
    """criteria 白名单键 + 实体状态集校验;空 criteria 允许(等价不限)。"""
    if criteria is None:
        return {}
    if not isinstance(criteria, dict):
        raise invalid_request("criteria 必须是对象")
    for key in criteria:
        if key not in CRITERIA_KEYS:
            raise invalid_request(f"非法的筛选条件键: {key}")
    statuses = criteria.get("statuses")
    if statuses is not None:
        if not isinstance(statuses, list) or not all(isinstance(s, str) for s in statuses):
            raise invalid_request("statuses 必须是字符串列表")
        valid = _STATUSES_BY_ENTITY[entity_type]
        for s in statuses:
            if s not in valid:
                raise invalid_request(f"非法的状态: {s}")
    if "updated_within_days" in criteria:
        days = criteria["updated_within_days"]
        if not isinstance(days, int) or isinstance(days, bool) or days < 1:
            raise invalid_request("updated_within_days 必须是 ≥1 的整数")
    if "keyword" in criteria:
        keyword = criteria["keyword"]
        if not isinstance(keyword, str) or len(keyword) > 100:
            raise invalid_request("keyword 不能超过 100 字符")
    if "view_mode" in criteria and criteria["view_mode"] not in VIEW_MODES:
        raise invalid_request("非法的 view_mode")
    if "assignee_id" in criteria:
        if entity_type != "task":
            raise invalid_request("assignee_id 仅任务视图支持")
        try:
            uuid.UUID(str(criteria["assignee_id"]))
        except (ValueError, AttributeError, TypeError):
            raise invalid_request("assignee_id 必须是合法 UUID")
    return criteria


def create_filter_view(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    entity_type: str | None,
    name: str | None,
    criteria: dict | None,
) -> ProjectFilterView:
    entity_type = _validate_entity_type(entity_type)
    name = _validate_name(name)
    criteria = _validate_criteria(entity_type, criteria)
    get_accessible_project(db, actor.id, project_id, min_level="viewer")
    duplicate = db.scalar(
        select(ProjectFilterView).where(
            ProjectFilterView.project_id == project_id,
            ProjectFilterView.user_id == actor.id,
            ProjectFilterView.entity_type == entity_type,
            ProjectFilterView.name == name,
        )
    )
    if duplicate is not None:
        raise conflict("同名筛选视图已存在")
    view = ProjectFilterView(
        project_id=project_id,
        user_id=actor.id,
        entity_type=entity_type,
        name=name,
        criteria=criteria,
    )
    db.add(view)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("同名筛选视图已存在")
    return view


def list_filter_views(
    db: Session, user: User, project_id: uuid.UUID, entity_type: str | None
) -> dict:
    """仅返回本人视图,按 entity_type 过滤。"""
    entity_type = _validate_entity_type(entity_type)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    rows = db.scalars(
        select(ProjectFilterView)
        .where(
            ProjectFilterView.project_id == project_id,
            ProjectFilterView.user_id == user.id,
            ProjectFilterView.entity_type == entity_type,
        )
        .order_by(ProjectFilterView.created_at)
    ).all()
    return {"items": [_view_dict(view) for view in rows]}


def get_filter_view(db: Session, user: User, view_id: uuid.UUID) -> ProjectFilterView:
    return _get_owned(db, user, view_id)


def update_filter_view(
    db: Session,
    actor: User,
    view_id: uuid.UUID,
    name: str | None = None,
    criteria: dict | None = None,
    name_set: bool = False,
    criteria_set: bool = False,
) -> ProjectFilterView:
    view = _get_owned(db, actor, view_id)
    if name_set:
        view.name = _validate_name(name)
    if criteria_set:
        view.criteria = _validate_criteria(view.entity_type, criteria)
    db.commit()
    return view


def delete_filter_view(db: Session, actor: User, view_id: uuid.UUID) -> None:
    """物理删除(与软删需求不同):删除后同名可重建。"""
    view = _get_owned(db, actor, view_id)
    db.delete(view)
    db.commit()


def _get_owned(db: Session, actor: User, view_id: uuid.UUID) -> ProjectFilterView:
    """按 (id, user_id) 过滤:非本人视图一律 not_found,不泄露存在性。"""
    view = db.scalar(
        select(ProjectFilterView).where(
            ProjectFilterView.id == view_id,
            ProjectFilterView.user_id == actor.id,
        )
    )
    if view is None:
        raise not_found("筛选视图不存在")
    return view
