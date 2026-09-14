"""多态服务:comment / activity / reference(规格书 §2.3 / §3.3;ADR 0003 任务取消评论区)。

- 目标解析:requirement / task / document / project;user 目标暂不支持
  (comment/activity 的 project_id NOT NULL,工作区级实体无处挂载,ticket 02 已知缺口)
- 评论目标:task 拒绝(invalid_request);任务的活动/引用/附件/关注保留
- 评论删除:editor 仅自己的,owner/admin 任意(§5.1)
- reference 双向列表(from/to 任一命中);from 与 to 必须在同一项目
- activity 只追加不可变(CreatedAtMixin)
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Activity, Comment, Document, Project, Reference, Repository, Requirement, Task, User
from .labels import TARGET_TYPE_CN
from .pagination import page_result
from .permissions import get_accessible_project, get_project_role, is_admin, require_project_role
from .user_profiles import avatar_url, display_name

TARGET_TYPES = ("requirement", "task", "document", "repository", "project")
REFERENCE_TYPES = ("derives", "documents", "implements", "mentions")

_TARGET_MODELS = {
    "requirement": Requirement,
    "task": Task,
    "document": Document,
    "repository": Repository,
}


def resolve_target(db: Session, target_type: str, target_id, user: User | None = None) -> Project:
    """目标实体 → 其所属项目(ADR 0002:实体目标按短码寻址,project/repository 仍按 UUID)。

    五类实体目标:有 user 时按其可访问项目消歧(跨项目同码);无 user 时全库唯一直接返回。
    """
    if target_type not in TARGET_TYPES:
        raise invalid_request(f"不支持的目标类型: {target_type}")
    if target_type == "project":
        project = db.scalar(
            select(Project).where(
                Project.id == uuid.UUID(str(target_id)), Project.deleted_at.is_(None)
            )
        )
        if project is None:
            raise not_found("目标不存在")
        return project
    if target_type == "repository":
        repo = db.scalar(
            select(Repository).where(
                Repository.id == uuid.UUID(str(target_id)), Repository.deleted_at.is_(None)
            )
        )
        if repo is None:
            raise not_found("目标不存在")
        return db.scalar(select(Project).where(Project.id == repo.project_id))
    from .short_codes import require_valid_code
    from .short_code_lookup import resolve_by_code

    entity, project = resolve_by_code(db, user, target_type, target_id)
    return project


def record_activity(
    db: Session,
    project_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    summary: str | None = None,
) -> Activity:
    """业务变更审计:所有变更即时记 activity(§3.3 / §6.2 写入管线第一层),并生成站内通知。

    target_id 列为字符串:实体目标存短码,project/repository 目标存 UUID 字符串(ADR 0002)。
    """
    activity = Activity(
        project_id=project_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=str(target_id),
        action=action,
        summary=summary,
    )
    db.add(activity)
    from .notifications import notify_activity

    notify_activity(db, activity)
    return activity


def _user_name(db: Session, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return "系统"
    user = db.get(User, user_id)
    return display_name(user)


def _user_avatar(db: Session, user_id: uuid.UUID | None) -> str | None:
    return avatar_url(db.get(User, user_id)) if user_id else None


def _comment_dict(db: Session, c: Comment) -> dict:
    return {
        "id": str(c.id),
        "target_type": c.target_type,
        "target_id": c.target_id,
        "body": c.body,
        "author_id": str(c.author_id),
        "author": _user_name(db, c.author_id),
        "author_avatar": _user_avatar(db, c.author_id),
        "created_at": c.created_at.isoformat(),
    }


def _activity_dict(db: Session, a: Activity) -> dict:
    return {
        "id": str(a.id),
        "target_type": a.target_type,
        "target_id": a.target_id,
        "actor_id": str(a.actor_id) if a.actor_id else None,
        "actor": _user_name(db, a.actor_id),
        "actor_avatar": _user_avatar(db, a.actor_id),
        "action": a.action,
        "summary": a.summary,
        "created_at": a.created_at.isoformat(),
    }


def create_comment(db: Session, actor: User, target_type: str, target_id: str, body: str) -> Comment:
    body = body.strip()
    if not body:
        raise invalid_request("评论内容不能为空")
    if target_type == "task":
        raise invalid_request("任务已取消评论区,请在关联需求下评论")
    project = resolve_target(db, target_type, target_id, user=actor)
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
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int
) -> dict:
    if target_type == "task":
        raise invalid_request("任务已取消评论区,请在关联需求下评论")
    project = resolve_target(db, target_type, target_id, user=user)
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
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int
) -> dict:
    project = resolve_target(db, target_type, target_id, user=user)
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
    from_id: str,
    to_type: str,
    to_id: str,
    ref_type: str,
) -> Reference:
    if ref_type not in REFERENCE_TYPES:
        raise invalid_request(f"不支持的引用类型: {ref_type}")
    if from_type == to_type and from_id == to_id:
        raise invalid_request("不能引用自身")
    from_project = resolve_target(db, from_type, from_id, user=actor)
    to_project = resolve_target(db, to_type, to_id, user=actor)
    if from_project.id != to_project.id:
        raise invalid_request("引用双方必须属于同一项目")
    require_project_role(db, actor.id, from_project.id, min_level="editor")
    dup = db.scalar(
        select(Reference).where(
            Reference.project_id == from_project.id,
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
    to_label = TARGET_TYPE_CN.get(to_type, to_type)
    to_title = _target_title(db, to_type, to_id)
    summary = f"引用 {to_label}《{to_title}》" if to_title else f"引用 {to_label}(已删除)"
    record_activity(db, from_project.id, actor.id, from_type, from_id, "reference", summary)
    db.commit()
    return ref


def _target_title(db: Session, target_type: str, target_id) -> str | None:
    """引用目标的当前可读标题;目标不存在或无标题字段时返回 None(短码/UUID 兼容)。"""
    if target_type == "project":
        target = db.get(Project, target_id)
        return target.name if target else None
    if target_type == "repository":
        target = db.get(Repository, target_id)
        return target.name if target else None
    model = _TARGET_MODELS.get(target_type)
    if model is None:
        return None
    target = db.scalar(select(model).where(model.code == target_id).limit(1))
    if target is None:
        return None
    return getattr(target, "title", None) or getattr(target, "name", None)


def _ref_dict(db: Session, r: Reference) -> dict:
    def target_label(target_type: str, target_id) -> tuple[str, str | None]:
        if target_type == "project":
            target = db.get(Project, target_id)
            return (target.name if target else "已删除", None)
        if target_type == "repository":
            target = db.get(Repository, target_id)
            return (target.name if target else "已删除", None)
        model = _TARGET_MODELS.get(target_type)
        target = (
            db.scalar(select(model).where(model.code == target_id).limit(1)) if model else None
        )
        if target is None:
            return ("已删除", None)
        return (
            getattr(target, "title", None) or getattr(target, "name", None) or "已删除",
            getattr(target, "doc_type", None),
        )

    from_title, from_module = target_label(r.from_type, r.from_id)
    to_title, to_module = target_label(r.to_type, r.to_id)
    return {
        "id": str(r.id),
        "from_type": r.from_type,
        "from_id": r.from_id,
        "to_type": r.to_type,
        "to_id": r.to_id,
        "type": r.type,
        "from_title": from_title,
        "to_title": to_title,
        "from_module": from_module,
        "to_module": to_module,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
    }


def list_references(
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int
) -> dict:
    """双向:from 或 to 命中目标均返回(引用面板)。"""
    project = resolve_target(db, target_type, target_id, user=user)
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
