"""Repository record service.

The service deliberately limits itself to registration and lifecycle metadata:
it does not contact, clone, synchronize, or index a remote repository.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Repository, User
from ..models.repository import REPOSITORY_VCS_TYPES
from .permissions import get_accessible_project, require_project_role
from .polymorphic import record_activity

_CREATE_FIELDS = {"name", "vcs_type", "other_vcs_type", "url", "description", "default_branch"}
_UPDATE_FIELDS = _CREATE_FIELDS
_SCP_GIT_URL = re.compile(r"^[^/@:\\s]+@[^/:\s]+:[^\s]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(value: object, field: str, max_length: int | None = None, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise invalid_request(f"{field} 不能为空")
        return None
    if not isinstance(value, str):
        raise invalid_request(f"{field} 必须是字符串")
    result = value.strip()
    if not result:
        if required:
            raise invalid_request(f"{field} 不能为空")
        return None
    if max_length is not None and len(result) > max_length:
        raise invalid_request(f"{field} 过长")
    return result


def _reject_unknown_fields(payload: dict, allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise invalid_request(f"不支持的字段: {', '.join(unknown)}")


def _has_embedded_credentials(value: str) -> bool:
    # An SSH username selects the remote account (for example
    # ssh://git@host/repo) and is part of the repository locator; a password
    # or HTTP(S) userinfo is an embedded credential and must not be stored.
    parsed = urlsplit(value)
    if parsed.password or (parsed.username and parsed.scheme.casefold() not in {"ssh", "svn+ssh"}):
        return True
    return bool(re.search(r"(?:[?&#](?:access_)?token|[?&#]password|[?&#]api[_-]?key)=", value, re.I))


def _normalise_url(value: str) -> str:
    """Trim input and remove a non-root trailing slash without changing paths."""
    if _SCP_GIT_URL.fullmatch(value):
        user_host, path = value.split(":", 1)
        return f"{user_host.casefold()}:{path.rstrip('/')}"
    parsed = urlsplit(value)
    if parsed.scheme and parsed.netloc:
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, parsed.query, parsed.fragment))
    return value.rstrip("/") if value != "/" else value


def _validate_url(vcs_type: str, value: object) -> tuple[str, str]:
    url = _clean(value, "仓库地址", 2048, required=True)
    assert url is not None
    if any(char.isspace() for char in url) or _has_embedded_credentials(url):
        raise invalid_request("仓库地址不能包含嵌入式凭据或空白字符")
    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    if vcs_type == "git":
        is_windows_path = bool(re.match(r"^[A-Za-z]:[\\/]", url)) or url.startswith("\\\\")
        is_file_path = (not scheme and not _SCP_GIT_URL.fullmatch(url)) or is_windows_path
        if not (scheme in {"http", "https", "ssh", "file"} or _SCP_GIT_URL.fullmatch(url) or is_file_path):
            raise invalid_request("Git 仓库地址必须是 HTTP(S)、SSH、git@host:path 或本地路径")
    elif vcs_type == "svn":
        if scheme not in {"http", "https", "svn", "svn+ssh"} or not parsed.netloc:
            raise invalid_request("SVN 仓库地址必须是 HTTP(S)、svn:// 或 svn+ssh:// 地址")
    return url, _normalise_url(url)


def _validate_payload(payload: dict, *, creating: bool, current: Repository | None = None) -> dict:
    _reject_unknown_fields(payload, _CREATE_FIELDS if creating else _UPDATE_FIELDS)
    values: dict[str, object] = {}
    vcs_type = payload.get("vcs_type", current.vcs_type if current else None)
    if vcs_type not in REPOSITORY_VCS_TYPES:
        raise invalid_request("vcs_type 必须是 git、svn 或 other")
    values["vcs_type"] = vcs_type
    other_value = payload.get("other_vcs_type", current.other_vcs_type if current else None)
    if vcs_type != "other" and "vcs_type" in payload:
        other_value = None
    other_vcs_type = _clean(other_value, "其他版本控制类型", 64, required=vcs_type == "other")
    if vcs_type != "other" and other_vcs_type is not None:
        raise invalid_request("仅 vcs_type=other 时可填写 other_vcs_type")
    values["other_vcs_type"] = other_vcs_type if vcs_type == "other" else None
    if creating or "name" in payload:
        values["name"] = _clean(payload.get("name"), "名称", 128, required=True)
    if creating or "url" in payload or "vcs_type" in payload:
        raw_url = payload.get("url", current.url if current else None)
        values["url"], values["normalized_url"] = _validate_url(vcs_type, raw_url)
    for field, label, limit in (("description", "用途备注", 1000), ("default_branch", "默认分支", 256)):
        if creating or field in payload:
            values[field] = _clean(payload.get(field), label, limit)
    return values


def _repository_dict(repository: Repository) -> dict:
    return {
        "id": str(repository.id),
        "project_id": str(repository.project_id),
        "name": repository.name,
        "vcs_type": repository.vcs_type,
        "other_vcs_type": repository.other_vcs_type,
        "url": repository.url,
        "description": repository.description,
        "default_branch": repository.default_branch,
        "created_by": str(repository.created_by) if repository.created_by else None,
        "created_at": repository.created_at.isoformat(),
        "updated_at": repository.updated_at.isoformat(),
        "deleted_at": repository.deleted_at.isoformat() if repository.deleted_at else None,
    }


def _visible_repository(db: Session, user: User, repository_id: uuid.UUID, *, editable: bool = False, include_deleted: bool = False) -> Repository:
    repository = db.get(Repository, repository_id)
    if repository is None or (repository.deleted_at is not None and not include_deleted):
        raise not_found("代码仓库不存在")
    if editable:
        require_project_role(db, user.id, repository.project_id, min_level="editor")
    else:
        get_accessible_project(db, user.id, repository.project_id, min_level="viewer")
    return repository


def _assert_unique(db: Session, repository: Repository, *, exclude_id: uuid.UUID | None = None) -> None:
    rows = db.scalars(select(Repository).where(
        Repository.project_id == repository.project_id,
        Repository.vcs_type == repository.vcs_type,
        Repository.normalized_url == repository.normalized_url,
        Repository.deleted_at.is_(None),
    )).all()
    if any(row.id != exclude_id for row in rows):
        raise conflict("同一项目中已登记相同版本控制类型和地址的代码仓库")


def create_repository(db: Session, actor: User, project_id: uuid.UUID, payload: dict) -> Repository:
    require_project_role(db, actor.id, project_id, min_level="editor")
    values = _validate_payload(payload, creating=True)
    repository = Repository(project_id=project_id, created_by=actor.id, **values)
    db.add(repository)
    db.flush()
    _assert_unique(db, repository, exclude_id=repository.id)
    record_activity(db, project_id, actor.id, "repository", repository.id, "create", f"创建代码仓库 {repository.name}")
    db.commit()
    return repository


def list_repositories(db: Session, user: User, project_id: uuid.UUID, *, deleted: bool = False) -> list[dict]:
    if deleted:
        require_project_role(db, user.id, project_id, min_level="editor")
    else:
        get_accessible_project(db, user.id, project_id, min_level="viewer")
    rows = db.scalars(select(Repository).where(
        Repository.project_id == project_id,
        Repository.deleted_at.is_not(None) if deleted else Repository.deleted_at.is_(None),
    ).order_by(Repository.name, Repository.created_at)).all()
    return [_repository_dict(row) for row in rows]


def get_repository(db: Session, user: User, repository_id: uuid.UUID) -> dict:
    return _repository_dict(_visible_repository(db, user, repository_id))


def update_repository(db: Session, actor: User, repository_id: uuid.UUID, patch: dict) -> Repository:
    repository = _visible_repository(db, actor, repository_id, editable=True)
    if not patch:
        raise invalid_request("至少提供一个要更新的字段")
    values = _validate_payload(patch, creating=False, current=repository)
    for field, value in values.items():
        setattr(repository, field, value)
    _assert_unique(db, repository, exclude_id=repository.id)
    record_activity(db, repository.project_id, actor.id, "repository", repository.id, "update", f"更新代码仓库 {repository.name}")
    db.commit()
    return repository


def delete_repository(db: Session, actor: User, repository_id: uuid.UUID) -> None:
    repository = _visible_repository(db, actor, repository_id, editable=True)
    repository.deleted_at = _now()
    record_activity(db, repository.project_id, actor.id, "repository", repository.id, "delete", f"删除代码仓库 {repository.name}")
    db.commit()


def restore_repository(db: Session, actor: User, repository_id: uuid.UUID) -> Repository:
    repository = _visible_repository(db, actor, repository_id, editable=True, include_deleted=True)
    if repository.deleted_at is None:
        raise invalid_request("代码仓库尚未删除")
    _assert_unique(db, repository, exclude_id=repository.id)
    repository.deleted_at = None
    record_activity(db, repository.project_id, actor.id, "repository", repository.id, "restore", f"恢复代码仓库 {repository.name}")
    db.commit()
    return repository
