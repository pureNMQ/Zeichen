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
from ..models import Activity, Comment, Project, Reference, Repository, Requirement, Task, User
from .labels import TARGET_TYPE_CN
from .pagination import decode_cursor, page_result
from .permissions import get_accessible_project, get_project_role, is_admin, require_project_role
from .user_profiles import avatar_url, display_name

TARGET_TYPES = ("requirement", "task", "document", "repository", "project")
REFERENCE_TYPES = ("derives", "documents", "implements", "mentions")

_TARGET_MODELS = {
    "requirement": Requirement,
    "task": Task,
    "repository": Repository,
}


def resolve_target(
    db: Session, target_type: str, target_id, user: User | None = None,
    project_id: uuid.UUID | None = None,
) -> Project:
    """目标实体 → 其所属项目(ADR 0002:实体目标按短码寻址,project/repository 仍按 UUID)。

    五类实体目标:有 user 时按其可访问项目消歧(跨项目同码);显式 project_id 时
    项目内解析(REQ-55);无 user 时全库唯一直接返回。
    """
    if target_type not in TARGET_TYPES:
        raise invalid_request(f"不支持的目标类型: {target_type}")
    if target_type in {"project", "repository"}:
        try:
            target_id = uuid.UUID(str(target_id))
        except ValueError:
            raise invalid_request("target_id 必须是合法 UUID") from None
    if target_type == "project":
        project = db.scalar(
            select(Project).where(
                Project.id == target_id, Project.deleted_at.is_(None)
            )
        )
        if project is None or (project_id is not None and project.id != project_id):
            raise not_found("目标不存在")
        return project
    if target_type == "repository":
        repo = db.scalar(
            select(Repository).where(
                Repository.id == target_id, Repository.deleted_at.is_(None)
            )
        )
        if repo is None or (project_id is not None and repo.project_id != project_id):
            raise not_found("目标不存在")
        return db.scalar(select(Project).where(Project.id == repo.project_id))
    from .short_code_lookup import resolve_by_code

    _, project = resolve_by_code(db, user, target_type, target_id, project_id=project_id)
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
    """记录旧版审计，并把支持的需求和任务事实写入新版时间轴。

    target_id 列为字符串:实体目标存短码,project/repository 目标存 UUID 字符串(ADR 0002)。
    """
    activity = Activity(
        project_id=project_id,
        actor_id=actor_id,
        target_type=target_type,
        target_id=str(target_id),
        action=action,
        summary=summary,
        created_at=_now(),
    )
    db.add(activity)
    if target_type in {"requirement", "task"} and action in {
        "create", "update", "delete", "restore", "assign", "unassign", "reference", "blocker",
    }:
        from ..v2.resource_refs import ResourceKind, ResourceRef
        from ..v2.timeline import record_system_event

        source_task = str(target_id) if target_type == "task" else None
        task = db.get(Task, (project_id, source_task)) if source_task is not None else None
        requirement_id = str(target_id) if target_type == "requirement" else task.requirement_id if task else None
        if requirement_id is not None:
            record_system_event(
                db, actor_id, ResourceRef(project_id, ResourceKind.REQUIREMENT, requirement_id),
                event_type=f"{target_type}.{action}", event_data={"summary": summary}, source_task=source_task,
            )
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


def create_comment(
    db: Session, actor: User, target_type: str, target_id: str, body: str,
    project_id: uuid.UUID | None = None,
) -> Comment:
    body = body.strip()
    if not body:
        raise invalid_request("评论内容不能为空")
    if target_type == "task":
        raise invalid_request("任务已取消评论区,请在关联需求下评论")
    project = resolve_target(db, target_type, target_id, user=actor, project_id=project_id)
    require_project_role(db, actor.id, project.id, min_level="editor")
    comment = Comment(
        project_id=project.id,
        target_type=target_type,
        target_id=target_id,
        author_id=actor.id,
        body=body,
        created_by=actor.id,
        created_at=_now(),
    )
    db.add(comment)
    record_activity(db, project.id, actor.id, target_type, target_id, "comment", "添加评论")
    db.commit()
    return comment


def list_comments(
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int,
    project_id: uuid.UUID | None = None,
) -> dict:
    if target_type == "task":
        raise invalid_request("任务已取消评论区,请在关联需求下评论")
    project = resolve_target(db, target_type, target_id, user=user, project_id=project_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    filters = _filters(project.id, target_type, target_id)
    offset = decode_cursor(filters, cursor)
    rows = db.scalars(
        select(Comment)
        .where(
            Comment.project_id == project.id,
            Comment.target_type == target_type,
            Comment.target_id == target_id,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at, Comment.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_comment_dict(db, c) for c in rows]
    return page_result(items, offset, limit, filters)


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
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int,
    project_id: uuid.UUID | None = None,
) -> dict:
    project = resolve_target(db, target_type, target_id, user=user, project_id=project_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    filters = _filters(project.id, target_type, target_id)
    offset = decode_cursor(filters, cursor)
    rows = db.scalars(
        select(Activity)
        .where(
            Activity.project_id == project.id,
            Activity.target_type == target_type,
            Activity.target_id == target_id,
        )
        .order_by(Activity.created_at, Activity.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_activity_dict(db, a) for a in rows]
    return page_result(items, offset, limit, filters)


def resolve_reference_target(
    db: Session, actor: User, target_type: str, target_id: str, project_id: uuid.UUID | None,
) -> Project:
    if target_type != "document":
        return resolve_target(db, target_type, target_id, user=actor, project_id=project_id)

    from ..v2.resource_refs import ResourceKind, ResourceRef

    if project_id is None:
        raise invalid_request("Wiki 引用必须指定 project_id")
    project = get_accessible_project(db, actor.id, project_id, min_level="viewer")
    ResourceRef(project_id, ResourceKind.WIKI, target_id)
    title, _ = _target_label(db, project_id, target_type, target_id)
    if title is None:
        raise not_found("Wiki 不存在")
    return project


def create_reference(
    db: Session,
    actor: User,
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    ref_type: str,
    project_id: uuid.UUID | None = None,
) -> Reference:
    if ref_type not in REFERENCE_TYPES:
        raise invalid_request(f"不支持的引用类型: {ref_type}")
    if from_type == to_type and from_id == to_id:
        raise invalid_request("不能引用自身")
    from_project = resolve_reference_target(db, actor, from_type, from_id, project_id)
    to_project = resolve_reference_target(db, actor, to_type, to_id, project_id)
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
        created_at=_now(),
    )
    db.add(ref)
    to_label = TARGET_TYPE_CN.get(to_type, to_type)
    to_title, _ = _target_label(db, from_project.id, to_type, to_id)
    summary = f"引用 {to_label}《{to_title}》" if to_title else f"引用 {to_label}(已删除)"
    record_activity(db, from_project.id, actor.id, from_type, from_id, "reference", summary)
    db.commit()
    return ref


def _target_label(
    db: Session, project_id: uuid.UUID, target_type: str, target_id: str,
) -> tuple[str | None, str | None]:
    if target_type == "project":
        target = db.get(Project, project_id) if target_id == str(project_id) else None
        return (target.name, None) if target and target.deleted_at is None else (None, None)
    if target_type == "document":
        from ..v2.wiki import visible_wiki_codes
        from ..v2.wiki_models import Wiki

        title = db.scalar(select(Wiki.title).where(
            Wiki.project_id == project_id, Wiki.code == target_id, Wiki.code.in_(visible_wiki_codes(project_id)),
        ))
        return (title, "wiki") if title is not None else (None, None)
    if target_type == "repository":
        try:
            repository_id = uuid.UUID(str(target_id))
        except ValueError:
            return None, None
        target = db.get(Repository, repository_id)
        if target and target.project_id == project_id and target.deleted_at is None:
            return target.name, None
        return None, None
    model = _TARGET_MODELS.get(target_type)
    if model is None:
        return None, None
    target = db.get(model, (project_id, target_id))
    if target is None or target.deleted_at is not None:
        return None, None
    if isinstance(target, Task):
        parent = db.get(Requirement, (project_id, target.requirement_id))
        if parent is None or parent.deleted_at is not None:
            return None, None
    return target.title, getattr(target, "doc_type", None)


def _ref_dict(db: Session, r: Reference) -> dict:
    from_title, from_module = _target_label(db, r.project_id, r.from_type, r.from_id)
    to_title, to_module = _target_label(db, r.project_id, r.to_type, r.to_id)
    return {
        "id": str(r.id),
        "from_type": r.from_type,
        "from_id": r.from_id,
        "to_type": r.to_type,
        "to_id": r.to_id,
        "type": r.type,
        "from_title": from_title or "已删除",
        "to_title": to_title or "已删除",
        "from_module": from_module,
        "to_module": to_module,
        "created_by": str(r.created_by) if r.created_by else None,
        "created_at": r.created_at.isoformat(),
    }


def list_references(
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int,
    project_id: uuid.UUID | None = None,
) -> dict:
    """双向:from 或 to 命中目标均返回(引用面板)。"""
    project = resolve_reference_target(db, user, target_type, target_id, project_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    filters = _filters(project.id, target_type, target_id)
    offset = decode_cursor(filters, cursor)
    rows = db.scalars(
        select(Reference)
        .where(
            Reference.project_id == project.id,
            Reference.deleted_at.is_(None),
            or_(
                (Reference.from_type == target_type) & (Reference.from_id == target_id),
                (Reference.to_type == target_type) & (Reference.to_id == target_id),
            ),
        )
        .order_by(Reference.created_at, Reference.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_ref_dict(db, r) for r in rows]
    return page_result(items, offset, limit, filters)


def delete_reference(db: Session, actor: User, ref_id: uuid.UUID) -> None:
    ref = db.scalar(select(Reference).where(Reference.id == ref_id, Reference.deleted_at.is_(None)))
    if ref is None:
        raise not_found("引用不存在")
    project = db.scalar(select(Project).where(Project.id == ref.project_id))
    if project is not None:
        require_project_role(db, actor.id, project.id, min_level="editor")
    ref.deleted_at = _now()
    db.commit()


def _filters(project_id: uuid.UUID, target_type: str, target_id: str) -> dict:
    return {"project_id": str(project_id), "type": target_type, "id": str(target_id)}


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
