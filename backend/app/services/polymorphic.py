"""多态服务:comment / activity / reference(规格书 §2.3 / §3.3)。

- 目标解析:requirement / task / document / project;user 目标暂不支持
  (comment/activity 的 project_id NOT NULL,工作区级实体无处挂载,ticket 02 已知缺口)
- 评论删除:editor 仅自己的,owner/admin 任意(§5.1)
- reference 双向列表(from/to 任一命中);from 与 to 必须在同一项目
- activity 只追加不可变(CreatedAtMixin)
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Activity, CodeSymbol, Comment, Document, Project, Reference, Requirement, Task, User
from .pagination import page_result
from .permissions import get_accessible_project, get_project_role, is_admin, require_project_role

TARGET_TYPES = ("requirement", "task", "document", "code_symbol", "project")
REFERENCE_TYPES = ("derives", "documents", "implements", "mentions")

_TARGET_MODELS = {
    "requirement": Requirement,
    "task": Task,
    "document": Document,
    "code_symbol": CodeSymbol,
}


def resolve_target(db: Session, target_type: str, target_id: uuid.UUID) -> Project:
    """目标实体 → 其所属项目(目标不存在/已软删/类型不支持 → 404/400)。"""
    if target_type not in TARGET_TYPES:
        raise invalid_request(f"不支持的目标类型: {target_type}")
    if target_type == "project":
        project = db.scalar(
            select(Project).where(Project.id == target_id, Project.deleted_at.is_(None))
        )
        if project is None:
            raise not_found("目标不存在")
        return project
    model = _TARGET_MODELS[target_type]
    obj = db.scalar(
        select(model).where(model.id == target_id, model.deleted_at.is_(None))
    )
    if obj is None:
        raise not_found("目标不存在")
    project_id = obj.library.project_id if target_type == "code_symbol" else obj.project_id
    return db.scalar(select(Project).where(Project.id == project_id))


def record_activity(
    db: Session,
    project_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    summary: str | None = None,
) -> Activity:
    """业务变更审计:所有变更即时记 activity(§3.3 / §6.2 写入管线第一层)。"""
    activity = Activity(
        project_id=project_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        action=action,
        summary=summary,
    )
    db.add(activity)
    return activity


def _user_name(db: Session, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return "系统"
    user = db.get(User, user_id)
    return user.username if user else "已删除用户"


def _comment_dict(db: Session, c: Comment) -> dict:
    return {
        "id": str(c.id),
        "target_type": c.target_type,
        "target_id": str(c.target_id),
        "body": c.body,
        "author_id": str(c.author_id),
        "author": _user_name(db, c.author_id),
        "created_at": c.created_at.isoformat(),
    }


def _activity_dict(db: Session, a: Activity) -> dict:
    return {
        "id": str(a.id),
        "target_type": a.target_type,
        "target_id": str(a.target_id),
        "actor_id": str(a.actor_id) if a.actor_id else None,
        "actor": _user_name(db, a.actor_id),
        "action": a.action,
        "summary": a.summary,
        "created_at": a.created_at.isoformat(),
    }


def create_comment(
    db: Session, actor: User, target_type: str, target_id: uuid.UUID, body: str
) -> Comment:
    body = body.strip()
    if not body:
        raise invalid_request("评论内容不能为空")
    project = resolve_target(db, target_type, target_id)
    require_project_role(db, actor.id, project.id, min_level="editor")
    comment = Comment(
        project_id=project.id,
        target_type=target_type,
        target_id=target_id,
        author_id=actor.id,
        body=body,
        created_by=actor.id,
    )
    db.add(comment)
    record_activity(db, project.id, actor.id, target_type, target_id, "comment", "添加评论")
    db.commit()
    return comment


def list_comments(
    db: Session, user: User, target_type: str, target_id: uuid.UUID, cursor: str | None, limit: int
) -> dict:
    project = resolve_target(db, target_type, target_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    offset = _decode_offset({"type": target_type, "id": str(target_id)}, cursor, limit)
    rows = db.scalars(
        select(Comment)
        .where(
            Comment.target_type == target_type,
            Comment.target_id == target_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_comment_dict(db, c) for c in rows]
    return page_result(items, offset, limit, _filters(target_type, target_id))


def delete_comment(db: Session, actor: User, comment_id: uuid.UUID) -> None:
    comment = db.scalar(
        select(Comment).where(Comment.id == comment_id, Comment.deleted_at.is_(None))
    )
    if comment is None:
        raise not_found("评论不存在")
    project = db.scalar(select(Project).where(Project.id == comment.project_id))
    role = get_project_role(db, actor.id, project.id) if project else None
    is_owner = role == "owner" or is_admin(db, actor.id)
    if comment.author_id != actor.id and not is_owner:
        raise permission_denied("仅可删除自己的评论")
    comment.deleted_at = _now()
    db.commit()


def list_activity(
    db: Session, user: User, target_type: str, target_id: uuid.UUID, cursor: str | None, limit: int
) -> dict:
    project = resolve_target(db, target_type, target_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    offset = _decode_offset({"type": target_type, "id": str(target_id)}, cursor, limit)
    rows = db.scalars(
        select(Activity)
        .where(Activity.target_type == target_type, Activity.target_id == target_id)
        .order_by(Activity.created_at)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_activity_dict(db, a) for a in rows]
    return page_result(items, offset, limit, _filters(target_type, target_id))


def create_reference(
    db: Session,
    actor: User,
    from_type: str,
    from_id: uuid.UUID,
    to_type: str,
    to_id: uuid.UUID,
    ref_type: str,
) -> Reference:
    if ref_type not in REFERENCE_TYPES:
        raise invalid_request(f"不支持的引用类型: {ref_type}")
    if from_type == to_type and from_id == to_id:
        raise invalid_request("不能引用自身")
    from_project = resolve_target(db, from_type, from_id)
    to_project = resolve_target(db, to_type, to_id)
    if from_project.id != to_project.id:
        raise invalid_request("引用双方必须属于同一项目")
    require_project_role(db, actor.id, from_project.id, min_level="editor")
    dup = db.scalar(
        select(Reference).where(
            Reference.from_type == from_type,
            Reference.from_id == from_id,
            Reference.to_type == to_type,
            Reference.to_id == to_id,
            Reference.deleted_at.is_(None),
        )
    )
    if dup is not None:
        raise conflict("该引用已存在")
    ref = Reference(
        project_id=from_project.id,
        from_type=from_type,
        from_id=from_id,
        to_type=to_type,
        to_id=to_id,
        type=ref_type,
        created_by=actor.id,
    )
    db.add(ref)
    record_activity(
        db, from_project.id, actor.id, from_type, from_id, "reference", f"引用 {to_type}:{to_id}"
    )
    db.commit()
    return ref


def _ref_dict(db: Session, r: Reference) -> dict:
    return {
        "id": str(r.id),
        "from_type": r.from_type,
        "from_id": str(r.from_id),
        "to_type": r.to_type,
        "to_id": str(r.to_id),
        "type": r.type,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
    }


def list_references(
    db: Session, user: User, target_type: str, target_id: uuid.UUID, cursor: str | None, limit: int
) -> dict:
    """双向:from 或 to 命中目标均返回(引用面板)。"""
    project = resolve_target(db, target_type, target_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    offset = _decode_offset({"type": target_type, "id": str(target_id)}, cursor, limit)
    rows = db.scalars(
        select(Reference)
        .where(
            Reference.deleted_at.is_(None),
            or_(
                (Reference.from_type == target_type) & (Reference.from_id == target_id),
                (Reference.to_type == target_type) & (Reference.to_id == target_id),
            ),
        )
        .order_by(Reference.created_at)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_ref_dict(db, r) for r in rows]
    return page_result(items, offset, limit, _filters(target_type, target_id))


def delete_reference(db: Session, actor: User, ref_id: uuid.UUID) -> None:
    ref = db.scalar(select(Reference).where(Reference.id == ref_id, Reference.deleted_at.is_(None)))
    if ref is None:
        raise not_found("引用不存在")
    project = db.scalar(select(Project).where(Project.id == ref.project_id))
    if project is not None:
        require_project_role(db, actor.id, project.id, min_level="editor")
    ref.deleted_at = _now()
    db.commit()


def _filters(target_type: str, target_id: uuid.UUID) -> dict:
    return {"type": target_type, "id": str(target_id)}


def _decode_offset(filters: dict, cursor: str | None, limit: int) -> int:
    from .pagination import decode_cursor

    return decode_cursor(filters, cursor)


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
