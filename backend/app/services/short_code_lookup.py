"""短码跨项目解析(ADR 0002):短码仅项目内唯一,无项目上下文时按用户可访问项目消歧。

- 0 命中 → not_found;格式非法 → invalid_request(旧 UUID 自然落入)
- 多命中(用户在多个项目各有同码实体)→ invalid_request,提示补充项目上下文
- 显式传 project_id(REQ-55 消歧通道)→ 严格项目内解析,先校验项目访问权
- 命中且用户对项目有查看权 → 返回 (实体, project);权限校验细节由调用方完成
"""

from sqlalchemy.orm import Session

from ..errors import invalid_request, not_found
from ..models import Document, Requirement, Task, User
from .permissions import get_accessible_project
from .projects import list_projects
from .short_codes import require_valid_code

_TARGET_MODELS = {
    "requirement": Requirement,
    "task": Task,
    "document": Document,
    # glossary 已并入 wiki(REQ-59):TERM-n 仍按 document 泛型寻址
    "glossary_term": Document,
}


def resolve_by_code(db: Session, user: User, entity_type: str, code: str, project_id=None):
    """解析短码 → (实体, Project);未删除实体。

    project_id 为空时在用户可访问项目内消歧(多命中 invalid_request);
    显式给定 project_id 时仅在该项目内查找(REQ-55:跨项目同码的消歧通道)。
    """
    require_valid_code(entity_type, code)
    model = _TARGET_MODELS[entity_type]
    from sqlalchemy import select

    if project_id is not None:
        project = get_accessible_project(db, user.id, project_id, min_level="viewer")
        entity = db.scalar(
            select(model).where(
                model.code == code,
                model.project_id == project_id,
                model.deleted_at.is_(None),
            )
        )
        if entity is None:
            raise not_found("目标不存在")
        return entity, project
    projects = [p for p, _role in list_projects(db, user)]
    if not projects:
        raise not_found("目标不存在")
    rows = db.scalars(
        select(model).where(
            model.code == code,
            model.project_id.in_([p.id for p in projects]),
            model.deleted_at.is_(None),
        )
    ).all()
    if not rows:
        raise not_found("目标不存在")
    if len(rows) > 1:
        names = ", ".join(p.name for p in projects if any(r.project_id == p.id for r in rows))
        raise invalid_request(f"短码 {code} 在多个项目中存在({names}),请补充 project_id 或通过项目内接口访问")
    entity = rows[0]
    project = next(p for p in projects if p.id == entity.project_id)
    return entity, project
