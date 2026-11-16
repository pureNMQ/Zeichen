"""User profile and avatar management."""

import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import invalid_request, not_found, permission_denied
from ..models import Attachment, User
from ..services.permissions import is_admin

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def display_name(user: User | None) -> str:
    if user is None:
        return "已删除用户"
    return (user.nickname or "").strip() or user.username


def avatar_url(user: User | None) -> str | None:
    return f"/api/users/{user.id}/avatar?v={user.avatar}" if user and user.avatar else None


def payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "nickname": user.nickname,
        "avatar": avatar_url(user),
        "display_name": display_name(user),
        "is_agent": user.is_agent,
    }


def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise not_found("用户不存在")
    return user


def _can_edit_profile(db: Session, actor: User, target: User) -> bool:
    """本人 / 工作区 admin / 附属 Agent 的主人(ADR 0004)。"""
    if actor.id == target.id:
        return True
    if is_admin(db, actor.id):
        return True
    return bool(target.is_agent and target.owner_id == actor.id and target.deleted_at is None)


def update_profile(db: Session, actor: User, target_id: uuid.UUID, nickname: str | None) -> User:
    target = get_user(db, target_id)
    if not _can_edit_profile(db, actor, target):
        raise permission_denied("只能修改自己的资料")
    target.nickname = nickname.strip() if nickname is not None and nickname.strip() else None
    db.commit()
    db.refresh(target)
    return target


def _attachment(db: Session, user: User) -> Attachment | None:
    if not user.avatar:
        return None
    return db.scalar(
        select(Attachment).where(
            Attachment.id == user.avatar,
            Attachment.target_type == "user",
            Attachment.target_id == str(user.id),
            Attachment.deleted_at.is_(None),
        )
    )


async def set_avatar(db: Session, actor: User, target_id: uuid.UUID, upload: UploadFile) -> User:
    target = get_user(db, target_id)
    if not _can_edit_profile(db, actor, target):
        raise permission_denied("只能修改自己的头像")
    if upload.content_type not in ALLOWED_AVATAR_TYPES:
        raise invalid_request("头像必须是 JPEG、PNG、GIF 或 WebP 图片")
    data = await upload.read(get_settings().attachment_max_bytes + 1)
    if not data:
        raise invalid_request("头像文件不能为空")
    if len(data) > get_settings().attachment_max_bytes:
        raise invalid_request("头像文件不能超过 20MB")
    signatures = {
        "image/jpeg": lambda value: value.startswith(b"\xff\xd8\xff"),
        "image/png": lambda value: value.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": lambda value: value.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": lambda value: len(value) >= 12 and value.startswith(b"RIFF") and value[8:12] == b"WEBP",
    }
    if not signatures[upload.content_type](data):
        raise invalid_request("头像文件内容与图片类型不匹配")

    root: Path = get_settings().attachment_storage_dir
    root.mkdir(parents=True, exist_ok=True)
    attachment_id = uuid.uuid4()
    suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}[upload.content_type]
    path = root / f"{attachment_id}{suffix}"
    path.write_bytes(data)

    old = _attachment(db, target)
    if old is not None:
        old.deleted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    attachment = Attachment(
        id=attachment_id,
        file_name=upload.filename or f"avatar{suffix}",
        size=len(data),
        storage_path=str(path),
        created_by=actor.id,
        project_id=None,
        target_type="user",
        target_id=str(target.id),
    )
    db.add(attachment)
    target.avatar = attachment_id
    db.commit()
    db.refresh(target)
    return target


def remove_avatar(db: Session, actor: User, target_id: uuid.UUID) -> User:
    """与 set_avatar 同一判权口径:本人 / admin / 附属 Agent 的主人。"""
    target = get_user(db, target_id)
    if not _can_edit_profile(db, actor, target):
        raise permission_denied("只能修改自己的头像")
    attachment = _attachment(db, target)
    if attachment is not None:
        attachment.deleted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    target.avatar = None
    db.commit()
    db.refresh(target)
    return target


def read_avatar(db: Session, target_id: uuid.UUID) -> tuple[bytes, str]:
    user = get_user(db, target_id)
    attachment = _attachment(db, user)
    if attachment is None:
        raise not_found("头像不存在")
    path = Path(attachment.storage_path)
    if not path.is_file():
        raise not_found("头像不存在")
    suffix = path.suffix.lower()
    content_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}.get(suffix, "application/octet-stream")
    return path.read_bytes(), content_type
