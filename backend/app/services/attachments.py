"""附件服务(规格书 §2.2 / §4.2 attachment.* / §8.2 配额)。

- 本地卷存储,按项目分桶(attachments/{project_id}/{attachment_id}.bin)
- 单文件 20MB、单项目配额 2GB,超限 conflict
- 软删跟随父实体:父实体软删时其附件一并软删;父实体恢复时附件不自动恢复
  (沿用业务软删语义,物理清理由运维级任务执行)
- target 解析复用 polymorphic.resolve_target 的项目归属与存在性校验
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import conflict, invalid_request, not_found, permission_denied
from ..models import Attachment, Project, User
from .pagination import page_result
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity, resolve_target

TARGET_TYPES = ("requirement", "task", "document", "project")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _storage_root() -> Path:
    return Path(get_settings().attachment_storage_dir)


def _attachment_path(project_id: uuid.UUID, attachment_id: uuid.UUID) -> Path:
    return _storage_root() / str(project_id) / f"{attachment_id}.bin"


def _attachment_dict(db: Session, a: Attachment) -> dict:
    return {
        "id": str(a.id),
        "target_type": a.target_type,
        "target_id": a.target_id,
        "file_name": a.file_name,
        "size": a.size,
        "created_by": str(a.created_by) if a.created_by else None,
        "created_at": a.created_at.isoformat(),
        "deleted_at": a.deleted_at.isoformat() if a.deleted_at else None,
    }


def _project_used_bytes(db: Session, project_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Attachment.size), 0)).where(
            Attachment.project_id == project_id, Attachment.deleted_at.is_(None)
        )
    ) or 0


def upload(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    target_type: str,
    target_id: str,
    file_name: str,
    data: bytes,
) -> Attachment:
    """写入附件文件并登记元数据;配额与单文件大小在上传前校验。"""
    if target_type not in TARGET_TYPES:
        raise invalid_request(f"不支持的目标类型: {target_type}")
    file_name = file_name.strip()
    if not file_name:
        raise invalid_request("文件名不能为空")
    if len(data) == 0:
        raise invalid_request("文件内容为空")
    settings = get_settings()
    if len(data) > settings.attachment_max_file_bytes:
        raise conflict(
            f"文件超过单文件上限({settings.attachment_max_file_bytes // (1024 * 1024)}MB)"
        )
    project = get_accessible_project(db, actor.id, project_id, min_level="editor")
    # target 必须属于该项目且存在(ADR 0002:实体目标按短码项目内寻址)
    from ..models import Document, Requirement, Task
    from .short_codes import require_valid_code

    if target_type in ("requirement", "task", "document"):
        require_valid_code(target_type, target_id)
        model = {"requirement": Requirement, "task": Task, "document": Document}[target_type]
        obj = db.scalar(
            select(model).where(model.project_id == project.id, model.code == target_id)
        )
        if obj is None or obj.deleted_at is not None:
            raise not_found("目标不存在")
    else:
        from .polymorphic import resolve_target

        resolve_target(db, target_type, target_id, user=actor)

    if _project_used_bytes(db, project.id) + len(data) > settings.attachment_project_quota_bytes:
        raise conflict("项目附件配额已满")

    attachment = Attachment(
        project_id=project.id,
        target_type=target_type,
        target_id=str(target_id),
        file_name=file_name,
        size=len(data),
        storage_path=str(_attachment_path(project.id, uuid.uuid4())),
        created_by=actor.id,
    )
    db.add(attachment)
    db.flush()
    path = _attachment_path(project.id, attachment.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    record_activity(
        db, project.id, actor.id, target_type, target_id, "attachment", f"上传附件 {file_name}"
    )
    db.commit()
    return attachment


def download(db: Session, user: User, attachment_id: uuid.UUID) -> tuple[str, bytes, str]:
    """读取附件字节与文件名;软删附件 404,父实体软删时附件保持可见性由调用方判断。"""
    a = db.scalar(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.deleted_at.is_(None))
    )
    if a is None:
        raise not_found("附件不存在")
    get_accessible_project(db, user.id, a.project_id, min_level="viewer")
    path = _attachment_path(a.project_id, a.id)
    if not path.is_file():
        raise not_found("附件文件已丢失")
    return a.file_name, path.read_bytes(), a.target_type + "/" + str(a.target_id)


def list_attachments(
    db: Session, user: User, target_type: str, target_id: str, cursor: str | None, limit: int,
    project_id: uuid.UUID | None = None,
) -> dict:
    from .pagination import decode_cursor

    project = resolve_target(db, target_type, target_id, user=user, project_id=project_id)
    get_accessible_project(db, user.id, project.id, min_level="viewer")
    filters = {"type": target_type, "id": str(target_id)}
    offset = decode_cursor(filters, cursor)
    rows = db.scalars(
        select(Attachment)
        .where(
            Attachment.target_type == target_type,
            Attachment.target_id == target_id,
            Attachment.deleted_at.is_(None),
        )
        .order_by(Attachment.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items = [_attachment_dict(db, a) for a in rows]
    return page_result(items, offset, limit, filters)


def soft_delete(db: Session, actor: User, attachment_id: uuid.UUID) -> None:
    a = db.scalar(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.deleted_at.is_(None))
    )
    if a is None:
        raise not_found("附件不存在")
    require_project_role(db, actor.id, a.project_id, min_level="editor")
    a.deleted_at = _now()
    record_activity(db, a.project_id, actor.id, a.target_type, a.target_id, "attachment_delete", f"删除附件 {a.file_name}")
    db.commit()


def restore(db: Session, actor: User, attachment_id: uuid.UUID) -> Attachment:
    a = db.scalar(select(Attachment).where(Attachment.id == attachment_id))
    if a is None or a.deleted_at is None:
        raise not_found("已删除的附件不存在")
    require_project_role(db, actor.id, a.project_id, min_level="editor")
    a.deleted_at = None
    record_activity(db, a.project_id, actor.id, a.target_type, a.target_id, "attachment_restore", f"恢复附件 {a.file_name}")
    db.commit()
    return a


def soft_delete_for_target(db: Session, project_id: uuid.UUID, target_type: str, target_id: str) -> int:
    """父实体软删时级联软删其附件(不 commit,随调用方事务)。返回受影响行数。"""
    rows = db.scalars(
        select(Attachment).where(
            Attachment.project_id == project_id,
            Attachment.target_type == target_type,
            Attachment.target_id == target_id,
            Attachment.deleted_at.is_(None),
        )
    ).all()
    now = _now()
    for a in rows:
        a.deleted_at = now
    return len(rows)
