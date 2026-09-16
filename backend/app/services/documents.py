"""Wiki 与词条文档的共享领域服务(ADR 0002:复合主键 (project_id, code),DOC/TERM/DIR 短码寻址)。"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Document, DocumentDirectory, DocumentVersion, Reference, User
from .pagination import decode_cursor, page_result
from .permissions import get_accessible_project, require_project_role
from .polymorphic import _ref_dict, record_activity

DOC_TYPES = ("wiki", "glossary")
DIRECTORY_MODULES = ("glossary",)
_UNSET = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _document_dict(db: Session, document: Document, warning: dict | None = None) -> dict:
    result = {
        "id": document.code,
        "node_kind": "document",
        "title": document.title,
        "doc_type": document.doc_type,
        "content": document.content,
        "metadata": copy.deepcopy(document.doc_metadata or {}),
        "project_id": str(document.project_id),
        "parent_id": document.parent_id,
        "directory_id": document.directory_id,
        "created_by": str(document.created_by) if document.created_by else None,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
        "deleted_at": document.deleted_at.isoformat() if document.deleted_at else None,
        "has_children": _document_has_children(db, document),
    }
    if warning is not None:
        result["reference_warning"] = warning
    return result


def _directory_dict(db: Session, directory: DocumentDirectory) -> dict:
    return {
        "id": directory.code,
        "node_kind": "directory",
        "name": directory.name,
        "title": directory.name,
        "module_type": directory.module_type,
        "project_id": str(directory.project_id),
        "parent_id": directory.parent_id,
        "created_by": str(directory.created_by) if directory.created_by else None,
        "created_at": directory.created_at.isoformat(),
        "updated_at": directory.updated_at.isoformat(),
        "deleted_at": directory.deleted_at.isoformat() if directory.deleted_at else None,
        "has_children": _directory_has_children(db, directory),
    }


def _version_dict(version: DocumentVersion) -> dict:
    return {
        "id": str(version.id),
        "version_no": version.version_no,
        "title": version.title,
        "content": version.content,
        "metadata": copy.deepcopy(version.doc_metadata or {}),
        "created_by": str(version.created_by) if version.created_by else None,
        "created_at": version.created_at.isoformat(),
    }


def _document_has_children(db: Session, document: Document) -> bool:
    if document.doc_type != "wiki":
        return False
    return db.scalar(
        select(Document.code).where(
            Document.project_id == document.project_id,
            Document.parent_id == document.code,
            Document.doc_type == "wiki",
            Document.deleted_at.is_(None),
        ).limit(1)
    ) is not None


def _directory_has_children(db: Session, directory: DocumentDirectory) -> bool:
    return (
        db.scalar(
            select(DocumentDirectory.code).where(
                DocumentDirectory.project_id == directory.project_id,
                DocumentDirectory.parent_id == directory.code,
                DocumentDirectory.deleted_at.is_(None),
            ).limit(1)
        ) is not None
        or db.scalar(
            select(Document.code).where(
                Document.project_id == directory.project_id,
                Document.directory_id == directory.code,
                Document.deleted_at.is_(None),
            ).limit(1)
        ) is not None
    )


def _require_module(module: str) -> None:
    if module not in DOC_TYPES:
        raise invalid_request("不支持的文档模块")


def _get_document_raw(db: Session, project_id: uuid.UUID, code: str) -> Document:
    from .short_codes import require_valid_code

    require_valid_code("document", code)
    document = db.scalar(
        select(Document).where(Document.project_id == project_id, Document.code == code)
    )
    if document is None:
        raise not_found("文档不存在")
    return document


def _get_directory_raw(db: Session, project_id: uuid.UUID, code: str) -> DocumentDirectory:
    from .short_codes import require_valid_code

    require_valid_code("document_directory", code)
    directory = db.scalar(
        select(DocumentDirectory).where(
            DocumentDirectory.project_id == project_id, DocumentDirectory.code == code
        )
    )
    if directory is None:
        raise not_found("目录不存在")
    return directory


def _visible_document(
    db: Session, user: User, document_id: str, include_deleted: bool = False,
    project_id: uuid.UUID | None = None,
) -> Document:
    from .short_code_lookup import resolve_by_code
    from .short_codes import require_valid_code

    require_valid_code("document", document_id)
    if include_deleted:
        # 恢复语义:允许已删行,扫描同码已删文档(显式 project_id 时仅限该项目)
        from ..models import Document as _Doc
        from .projects import list_projects

        if project_id is not None:
            get_accessible_project(db, user.id, project_id, min_level="viewer")
            project_ids = [project_id]
        else:
            projects = [p for p, _r in list_projects(db, user)]
            project_ids = [p.id for p in projects]
        rows = db.scalars(
            select(_Doc).where(
                _Doc.code == document_id,
                _Doc.project_id.in_(project_ids),
                _Doc.deleted_at.is_not(None),
            )
        ).all()
        if not rows:
            raise not_found("文档不存在")
        if len(rows) > 1:
            raise invalid_request(f"短码 {document_id} 在多个项目中存在,请通过项目内接口访问")
        document = rows[0]
        get_accessible_project(db, user.id, document.project_id, min_level="viewer")
        return document
    document, _project = resolve_by_code(db, user, "document", document_id, project_id=project_id)
    return document


def _editable_document(
    db: Session, user: User, document_id: str, include_deleted: bool = False,
    project_id: uuid.UUID | None = None,
) -> Document:
    document = _visible_document(db, user, document_id, include_deleted, project_id=project_id)
    require_project_role(db, user.id, document.project_id, min_level="editor")
    return document


def _editable_directory(
    db: Session, user: User, directory_id: str, include_deleted: bool = False,
    project_id: uuid.UUID | None = None,
) -> DocumentDirectory:
    from .short_code_lookup import resolve_by_code
    from .short_codes import require_valid_code

    require_valid_code("document_directory", directory_id)
    if include_deleted:
        from .projects import list_projects

        if project_id is not None:
            get_accessible_project(db, user.id, project_id, min_level="viewer")
            project_ids = [project_id]
        else:
            projects = [p for p, _r in list_projects(db, user)]
            project_ids = [p.id for p in projects]
        rows = db.scalars(
            select(DocumentDirectory).where(
                DocumentDirectory.code == directory_id,
                DocumentDirectory.project_id.in_(project_ids),
                DocumentDirectory.deleted_at.is_not(None),
            )
        ).all()
        if not rows:
            raise not_found("目录不存在")
        if len(rows) > 1:
            raise invalid_request(f"短码 {directory_id} 在多个项目中存在,请通过项目内接口访问")
        directory = rows[0]
    else:
        entity, _project = resolve_by_code(
            db, user, "document_directory", directory_id, project_id=project_id
        )
        directory = entity
    require_project_role(db, user.id, directory.project_id, min_level="editor")
    return directory


def get_document(
    db: Session, user: User, document_id: str, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Document:
    document = _visible_document(db, user, document_id, project_id=project_id)
    if module is not None and document.doc_type != module:
        raise not_found("文档不存在")
    return document


def get_directory(
    db: Session, user: User, directory_id: str, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> DocumentDirectory:
    from .short_code_lookup import resolve_by_code
    from .short_codes import require_valid_code

    require_valid_code("document_directory", directory_id)
    directory, _project = resolve_by_code(
        db, user, "document_directory", directory_id, project_id=project_id
    )
    get_accessible_project(db, user.id, directory.project_id, min_level="viewer")
    if module is not None and directory.module_type != module:
        raise not_found("目录不存在")
    return directory


def _validate_location(
    db: Session,
    project_id: uuid.UUID,
    doc_type: str,
    parent_id: str | None,
    directory_id: str | None,
    document_id: str | None = None,
) -> None:
    from .short_codes import require_valid_code

    if doc_type == "wiki":
        if directory_id is not None:
            raise invalid_request("Wiki 不能归属目录")
        if parent_id is None:
            return
        require_valid_code("document", parent_id)
        parent = _get_document_raw(db, project_id, parent_id)
        if parent.code == document_id:
            raise invalid_request("不能将 Wiki 移动到自身")
        if parent.deleted_at is not None or parent.project_id != project_id or parent.doc_type != "wiki":
            raise invalid_request("父 Wiki 必须属于同项目且未删除")
        if document_id is not None and parent.code in _wiki_subtree_ids(db, project_id, document_id):
            raise invalid_request("不能将 Wiki 移动到其后代")
        return

    if parent_id is not None:
        raise invalid_request("仅 Wiki 支持父文档")
    if directory_id is None:
        return
    require_valid_code("document_directory", directory_id)
    directory = _get_directory_raw(db, project_id, directory_id)
    if (
        directory.deleted_at is not None
        or directory.project_id != project_id
        or directory.module_type != doc_type
    ):
        raise invalid_request("目录必须属于同项目、同模块且未删除")


def _assert_document_title_unique(
    db: Session,
    project_id: uuid.UUID,
    doc_type: str,
    title: str,
    parent_id: str | None,
    directory_id: str | None,
    exclude_ids: set[str] | None = None,
) -> None:
    exclude_ids = exclude_ids or set()
    stmt = select(Document).where(
        Document.project_id == project_id,
        Document.doc_type == doc_type,
        Document.deleted_at.is_(None),
        Document.title == title,
    )
    if doc_type == "wiki":
        stmt = stmt.where(Document.parent_id == parent_id)
    existing = [row for row in db.scalars(stmt).all() if row.code not in exclude_ids]
    if existing:
        scope = "同级 Wiki" if doc_type == "wiki" else "同项目词条"
        raise conflict(f"{scope}标题已存在")


def _create_version(db: Session, document: Document, actor_id: uuid.UUID) -> DocumentVersion:
    next_no = (
        db.scalar(
            select(DocumentVersion.version_no)
            .where(
                DocumentVersion.project_id == document.project_id,
                DocumentVersion.document_id == document.code,
            )
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        )
        or 0
    ) + 1
    version = DocumentVersion(
        project_id=document.project_id,
        document_id=document.code,
        version_no=next_no,
        title=document.title,
        content=document.content or "",
        doc_metadata=copy.deepcopy(document.doc_metadata or {}),
        created_by=actor_id,
    )
    db.add(version)
    db.flush()
    old_ids = db.scalars(
        select(DocumentVersion.id)
        .where(
            DocumentVersion.project_id == document.project_id,
            DocumentVersion.document_id == document.code,
        )
        .order_by(DocumentVersion.version_no.desc())
        .offset(20)
    ).all()
    if old_ids:
        db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(old_ids)))
    return version


def create_document(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    title: str,
    doc_type: str,
    content: str | None,
    metadata: dict | None,
    parent_id: str | None = None,
    directory_id: str | None = None,
) -> Document:
    from .short_codes import allocate_code

    _require_module(doc_type)
    require_project_role(db, actor.id, project_id, min_level="editor")
    title = title.strip()
    if not title:
        raise invalid_request("标题不能为空")
    _validate_location(db, project_id, doc_type, parent_id, directory_id)
    _assert_document_title_unique(db, project_id, doc_type, title, parent_id, directory_id)
    doc_metadata = copy.deepcopy(metadata or {})
    code = allocate_code(db, project_id, "glossary_term" if doc_type == "glossary" else "document")
    document = Document(
        project_id=project_id,
        code=code,
        title=title,
        doc_type=doc_type,
        content=content or "",
        doc_metadata=doc_metadata,
        parent_id=parent_id,
        directory_id=directory_id,
        created_by=actor.id,
    )
    db.add(document)
    db.flush()
    _create_version(db, document, actor.id)
    record_activity(db, project_id, actor.id, "document", code, "create", f"创建 {doc_type} 文档")
    db.commit()
    return document


def update_document(
    db: Session,
    actor: User,
    document_id: str,
    title: str | None = None,
    content: str | None = None,
    metadata: object = _UNSET,
    project_id: uuid.UUID | None = None,
) -> tuple[Document, dict | None]:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    if title is not None:
        title = title.strip()
        if not title:
            raise invalid_request("标题不能为空")
        _assert_document_title_unique(
            db, document.project_id, document.doc_type, title, document.parent_id, document.directory_id, {document.code}
        )
        document.title = title
    if content is not None:
        document.content = content
    warning = None
    if metadata is not _UNSET:
        if not isinstance(metadata, dict):
            raise invalid_request("metadata 必须是对象")
        document.doc_metadata = copy.deepcopy(metadata)
    _create_version(db, document, actor.id)
    record_activity(db, document.project_id, actor.id, "document", document.code, "save", "保存文档版本")
    db.commit()
    return document, warning


def move_document(
    db: Session,
    actor: User,
    document_id: str,
    parent_id: str | None = None,
    directory_id: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Document:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    _validate_location(db, document.project_id, document.doc_type, parent_id, directory_id, document.code)
    _assert_document_title_unique(
        db, document.project_id, document.doc_type, document.title, parent_id, directory_id, {document.code}
    )
    document.parent_id = parent_id
    document.directory_id = directory_id
    record_activity(db, document.project_id, actor.id, "document", document.code, "move", "调整文档归属")
    db.commit()
    return document


def create_directory(
    db: Session,
    actor: User,
    project_id: uuid.UUID,
    module: str,
    name: str,
    parent_id: str | None = None,
) -> DocumentDirectory:
    from .short_codes import allocate_code

    if module not in DIRECTORY_MODULES:
        raise invalid_request("仅词典和 API 支持目录")
    require_project_role(db, actor.id, project_id, min_level="editor")
    name = name.strip()
    if not name:
        raise invalid_request("目录名称不能为空")
    _validate_directory_parent(db, project_id, module, parent_id)
    _assert_directory_name_unique(db, project_id, module, name, parent_id)
    directory = DocumentDirectory(
        project_id=project_id,
        code=allocate_code(db, project_id, "document_directory"),
        module_type=module,
        name=name,
        parent_id=parent_id,
        created_by=actor.id,
    )
    db.add(directory)
    db.flush()
    record_activity(db, project_id, actor.id, "project", project_id, "directory_create", f"创建 {module} 目录")
    db.commit()
    return directory


def _validate_directory_parent(
    db: Session,
    project_id: uuid.UUID,
    module: str,
    parent_id: str | None,
    directory_id: str | None = None,
) -> None:
    from .short_codes import require_valid_code

    if parent_id is None:
        return
    require_valid_code("document_directory", parent_id)
    parent = _get_directory_raw(db, project_id, parent_id)
    if parent.code == directory_id:
        raise invalid_request("不能将目录移动到自身")
    if parent.deleted_at is not None or parent.project_id != project_id or parent.module_type != module:
        raise invalid_request("父目录必须属于同项目、同模块且未删除")
    if directory_id is not None and parent.code in _directory_subtree_ids(db, project_id, directory_id):
        raise invalid_request("不能将目录移动到其后代")


def _assert_directory_name_unique(
    db: Session,
    project_id: uuid.UUID,
    module: str,
    name: str,
    parent_id: str | None,
    exclude_ids: set[str] | None = None,
) -> None:
    exclude_ids = exclude_ids or set()
    rows = db.scalars(
        select(DocumentDirectory).where(
            DocumentDirectory.project_id == project_id,
            DocumentDirectory.module_type == module,
            DocumentDirectory.parent_id == parent_id,
            DocumentDirectory.name == name,
            DocumentDirectory.deleted_at.is_(None),
        )
    ).all()
    if any(row.code not in exclude_ids for row in rows):
        raise conflict("同级目录名称已存在")


def rename_directory(
    db: Session, actor: User, directory_id: str, name: str,
    project_id: uuid.UUID | None = None,
) -> DocumentDirectory:
    directory = _editable_directory(db, actor, directory_id, project_id=project_id)
    name = name.strip()
    if not name:
        raise invalid_request("目录名称不能为空")
    _assert_directory_name_unique(
        db, directory.project_id, directory.module_type, name, directory.parent_id, {directory.code}
    )
    directory.name = name
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_rename", "重命名目录")
    db.commit()
    return directory


def move_directory(
    db: Session, actor: User, directory_id: str, parent_id: str | None,
    project_id: uuid.UUID | None = None,
) -> DocumentDirectory:
    directory = _editable_directory(db, actor, directory_id, project_id=project_id)
    _validate_directory_parent(db, directory.project_id, directory.module_type, parent_id, directory.code)
    _assert_directory_name_unique(
        db, directory.project_id, directory.module_type, directory.name, parent_id, {directory.code}
    )
    directory.parent_id = parent_id
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_move", "调整目录归属")
    db.commit()
    return directory


def _wiki_subtree_ids(db: Session, project_id: uuid.UUID, root_code: str) -> set[str]:
    found: set[str] = set()
    pending = [root_code]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(
            db.scalars(
                select(Document.code).where(
                    Document.project_id == project_id,
                    Document.parent_id == current,
                    Document.doc_type == "wiki",
                )
            ).all()
        )
    return found


def _directory_subtree_ids(db: Session, project_id: uuid.UUID, root_code: str) -> set[str]:
    found: set[str] = set()
    pending = [root_code]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(
            db.scalars(
                select(DocumentDirectory.code).where(
                    DocumentDirectory.project_id == project_id,
                    DocumentDirectory.parent_id == current,
                )
            ).all()
        )
    return found


def _directory_subtree_documents(db: Session, project_id: uuid.UUID, directory_codes: set[str]) -> set[str]:
    if not directory_codes:
        return set()
    return set(
        db.scalars(
            select(Document.code).where(
                Document.project_id == project_id, Document.directory_id.in_(directory_codes)
            )
        ).all()
    )


def delete_impact_document(
    db: Session, user: User, document_id: str, project_id: uuid.UUID | None = None
) -> dict:
    document = _visible_document(db, user, document_id, project_id=project_id)
    ids = _wiki_subtree_ids(db, document.project_id, document.code) if document.doc_type == "wiki" else {document.code}
    return {"documents": len(ids), "directories": 0}


def delete_impact_directory(
    db: Session, user: User, directory_id: str, project_id: uuid.UUID | None = None
) -> dict:
    directory = get_directory(db, user, directory_id, project_id=project_id)
    directory_ids = _directory_subtree_ids(db, directory.project_id, directory.code)
    return {"documents": len(_directory_subtree_documents(db, directory.project_id, directory_ids)), "directories": len(directory_ids)}


def delete_document(
    db: Session, actor: User, document_id: str, project_id: uuid.UUID | None = None
) -> None:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    ids = _wiki_subtree_ids(db, document.project_id, document.code) if document.doc_type == "wiki" else {document.code}
    rows = db.scalars(
        select(Document).where(
            Document.project_id == document.project_id,
            Document.code.in_(ids),
            Document.deleted_at.is_(None),
        )
    ).all()
    timestamp = _now()
    for row in rows:
        row.deleted_at = timestamp
    from .attachments import soft_delete_for_target

    for row in rows:
        soft_delete_for_target(db, row.project_id, "document", row.code)
    record_activity(db, document.project_id, actor.id, "document", document.code, "delete", f"递归删除 {len(rows)} 篇文档")
    db.commit()


def delete_directory(
    db: Session, actor: User, directory_id: str, project_id: uuid.UUID | None = None
) -> None:
    directory = _editable_directory(db, actor, directory_id, project_id=project_id)
    directory_ids = _directory_subtree_ids(db, directory.project_id, directory.code)
    document_codes = _directory_subtree_documents(db, directory.project_id, directory_ids)
    timestamp = _now()
    for row in db.scalars(
        select(Document).where(
            Document.project_id == directory.project_id,
            Document.code.in_(document_codes),
            Document.deleted_at.is_(None),
        )
    ).all():
        row.deleted_at = timestamp
    for row in db.scalars(
        select(DocumentDirectory).where(
            DocumentDirectory.project_id == directory.project_id,
            DocumentDirectory.code.in_(directory_ids),
            DocumentDirectory.deleted_at.is_(None),
        )
    ).all():
        row.deleted_at = timestamp
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_delete", "递归删除目录")
    db.commit()


def _validate_restore_documents(db: Session, documents: list[Document], directory_ids: set[str] | None = None) -> None:
    ids = {document.code for document in documents}
    directory_ids = directory_ids or set()
    for document in documents:
        if document.doc_type == "wiki" and document.parent_id and document.parent_id not in ids:
            parent = _get_document_raw(db, document.project_id, document.parent_id)
            if parent.deleted_at is not None:
                raise conflict("恢复失败：父 Wiki 已删除")
        if document.doc_type in DIRECTORY_MODULES and document.directory_id and document.directory_id not in directory_ids:
            directory = _get_directory_raw(db, document.project_id, document.directory_id)
            if directory.deleted_at is not None:
                raise conflict("恢复失败：所属目录已删除")
        _assert_document_title_unique(
            db,
            document.project_id,
            document.doc_type,
            document.title,
            document.parent_id,
            document.directory_id,
            ids,
        )


def _validate_restore_directories(db: Session, directories: list[DocumentDirectory]) -> None:
    ids = {directory.code for directory in directories}
    for directory in directories:
        if directory.parent_id and directory.parent_id not in ids:
            parent = _get_directory_raw(db, directory.project_id, directory.parent_id)
            if parent.deleted_at is not None:
                raise conflict("恢复失败：父目录已删除")
        _assert_directory_name_unique(
            db,
            directory.project_id,
            directory.module_type,
            directory.name,
            directory.parent_id,
            ids,
        )


def restore_document(
    db: Session, actor: User, document_id: str, project_id: uuid.UUID | None = None
) -> Document:
    document = _editable_document(
        db, actor, document_id, include_deleted=True, project_id=project_id
    )
    if document.deleted_at is None:
        raise not_found("已删除的文档不存在")
    ids = _wiki_subtree_ids(db, document.project_id, document.code) if document.doc_type == "wiki" else {document.code}
    rows = db.scalars(
        select(Document).where(
            Document.project_id == document.project_id, Document.code.in_(ids)
        )
    ).all()
    _validate_restore_documents(db, rows)
    for row in rows:
        row.deleted_at = None
    record_activity(db, document.project_id, actor.id, "document", document.code, "restore", f"递归恢复 {len(rows)} 篇文档")
    db.commit()
    return document


def restore_directory(
    db: Session, actor: User, directory_id: str, project_id: uuid.UUID | None = None
) -> DocumentDirectory:
    directory = _editable_directory(
        db, actor, directory_id, include_deleted=True, project_id=project_id
    )
    if directory.deleted_at is None:
        raise not_found("已删除的目录不存在")
    directory_ids = _directory_subtree_ids(db, directory.project_id, directory.code)
    directories = db.scalars(
        select(DocumentDirectory).where(
            DocumentDirectory.project_id == directory.project_id,
            DocumentDirectory.code.in_(directory_ids),
        )
    ).all()
    documents = db.scalars(
        select(Document).where(
            Document.project_id == directory.project_id,
            Document.directory_id.in_(directory_ids),
        )
    ).all()
    _validate_restore_directories(db, directories)
    _validate_restore_documents(db, documents, directory_ids)
    for row in directories:
        row.deleted_at = None
    for row in documents:
        row.deleted_at = None
    record_activity(db, directory.project_id, actor.id, "project", directory.project_id, "directory_restore", "递归恢复目录")
    db.commit()
    return directory


def list_module_children(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    module: str,
    parent_id: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    filters = {"project_id": str(project_id), "module": module, "parent_id": parent_id}
    offset = decode_cursor(filters, cursor)
    if module == "wiki":
        rows = db.scalars(
            select(Document).where(
                Document.project_id == project_id,
                Document.doc_type == "wiki",
                Document.parent_id == parent_id,
                Document.deleted_at.is_(None),
            )
        ).all()
        nodes = [_document_dict(db, row) for row in sorted(rows, key=lambda row: row.title.casefold())]
    else:
        directories = db.scalars(
            select(DocumentDirectory).where(
                DocumentDirectory.project_id == project_id,
                DocumentDirectory.module_type == module,
                DocumentDirectory.parent_id == parent_id,
                DocumentDirectory.deleted_at.is_(None),
            )
        ).all()
        documents = db.scalars(
            select(Document).where(
                Document.project_id == project_id,
                Document.doc_type == module,
                Document.directory_id == parent_id,
                Document.deleted_at.is_(None),
            )
        ).all()
        nodes = [_directory_dict(db, row) for row in sorted(directories, key=lambda row: row.name.casefold())]
        nodes += [_document_dict(db, row) for row in sorted(documents, key=lambda row: row.title.casefold())]
    page = nodes[offset:offset + limit]
    return page_result(page, offset, limit, filters)


def list_deleted_nodes(db: Session, user: User, project_id: uuid.UUID, module: str, cursor: str | None, limit: int) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    filters = {"project_id": str(project_id), "module": module, "deleted": True}
    offset = decode_cursor(filters, cursor)
    documents = db.scalars(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == module,
            Document.deleted_at.is_not(None),
        )
    ).all()
    nodes: list[dict] = [_document_dict(db, row) for row in documents]
    if module in DIRECTORY_MODULES:
        directories = db.scalars(
            select(DocumentDirectory).where(
                DocumentDirectory.project_id == project_id,
                DocumentDirectory.module_type == module,
                DocumentDirectory.deleted_at.is_not(None),
            )
        ).all()
        nodes += [_directory_dict(db, row) for row in directories]
    nodes.sort(key=lambda item: (item["node_kind"] != "directory", item["title"].casefold()))
    page = nodes[offset:offset + limit]
    return page_result(page, offset, limit, filters)


def ancestor_path(
    db: Session,
    user: User,
    project_id: uuid.UUID,
    module: str,
    node_kind: str,
    node_id: str,
) -> dict:
    _require_module(module)
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    if node_kind == "document":
        node = _visible_document(db, user, node_id, project_id=project_id)
        if node.project_id != project_id or node.doc_type != module:
            raise not_found("文档不存在")
        if module == "wiki":
            chain: list[Document] = []
            current: Document | None = node
            while current is not None:
                chain.append(current)
                current = (
                    _get_document_raw(db, project_id, current.parent_id) if current.parent_id else None
                )
            return {"items": [_document_dict(db, item) for item in reversed(chain)]}
        if node.directory_id is None:
            return {"items": [_document_dict(db, node)]}
        directory = get_directory(db, user, node.directory_id, module, project_id=project_id)
        chain_dirs = _directory_ancestors(db, directory)
        return {"items": [_directory_dict(db, item) for item in chain_dirs] + [_document_dict(db, node)]}
    if node_kind == "directory" and module in DIRECTORY_MODULES:
        directory = get_directory(db, user, node_id, module, project_id=project_id)
        if directory.project_id != project_id:
            raise not_found("目录不存在")
        return {"items": [_directory_dict(db, item) for item in _directory_ancestors(db, directory)]}
    raise invalid_request("节点类型无效")


def _directory_ancestors(db: Session, node: DocumentDirectory) -> list[DocumentDirectory]:
    chain: list[DocumentDirectory] = []
    current: DocumentDirectory | None = node
    while current is not None:
        chain.append(current)
        current = (
            _get_directory_raw(db, current.project_id, current.parent_id)
            if current.parent_id
            else None
        )
    return list(reversed(chain))


def list_versions(
    db: Session, user: User, document_id: str, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> list[dict]:
    document = get_document(db, user, document_id, module, project_id=project_id)
    versions = db.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.project_id == document.project_id,
            DocumentVersion.document_id == document.code,
        )
        .order_by(DocumentVersion.version_no.desc())
    ).all()
    return [_version_dict(version) for version in versions]


def rollback_document(
    db: Session, actor: User, document_id: str, version_no: int, module: str | None = None,
    project_id: uuid.UUID | None = None,
) -> Document:
    document = _editable_document(db, actor, document_id, project_id=project_id)
    if module is not None and document.doc_type != module:
        raise not_found("文档不存在")
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == document.project_id,
            DocumentVersion.document_id == document.code,
            DocumentVersion.version_no == version_no,
        )
    )
    if version is None:
        raise not_found("文档版本不存在")
    _assert_document_title_unique(
        db, document.project_id, document.doc_type, version.title, document.parent_id, document.directory_id, {document.code}
    )
    document.title = version.title
    document.content = version.content
    document.doc_metadata = copy.deepcopy(version.doc_metadata or {})
    created = _create_version(db, document, actor.id)
    record_activity(db, document.project_id, actor.id, "document", document.code, "rollback", f"回滚至版本 {version_no}（生成版本 {created.version_no}）")
    db.commit()
    return document


def get_glossary_term(db: Session, user: User, project_id: uuid.UUID, title: str) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.project_id == project_id,
            Document.doc_type == "glossary",
            Document.title == title,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise not_found("词条不存在")
    get_accessible_project(db, user.id, project_id, min_level="viewer")
    return document


def _reverse_references(db: Session, document: Document) -> dict:
    refs = db.scalars(
        select(Reference).where(
            Reference.deleted_at.is_(None),
            Reference.project_id == document.project_id,
            or_(
                (Reference.to_type == "document") & (Reference.to_id == document.code),
                (Reference.from_type == "document") & (Reference.from_id == document.code),
            ),
        )
    ).all()
    items = [_ref_dict(db, ref) for ref in refs]
    return {"count": len(items), "items": items}


def document_references(
    db: Session, user: User, document_id: str, module: str,
    project_id: uuid.UUID | None = None,
) -> dict:
    document = get_document(db, user, document_id, module, project_id=project_id)
    return _reverse_references(db, document)
