"""模块限定的文档工作台 HTTP API。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import (
    DirectoryCreate,
    DirectoryMove,
    DirectoryRename,
    DocumentCreate,
    DocumentMove,
    DocumentUpdate,
    RollbackBody,
)
from ..services import documents as service
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from .deps import current_user

router = APIRouter(prefix="/api", tags=["documents"])


def _page_limit(limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)) -> int:
    return limit


@router.get("/projects/{project_id}/documents/{module}/children")
def list_children(
    project_id: uuid.UUID,
    module: str,
    parent_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = Depends(_page_limit),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_module_children(db, user, project_id, module, parent_id, cursor, limit)


@router.get("/projects/{project_id}/documents/{module}/deleted")
def list_deleted(
    project_id: uuid.UUID,
    module: str,
    cursor: str | None = None,
    limit: int = Depends(_page_limit),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.list_deleted_nodes(db, user, project_id, module, cursor, limit)


@router.get("/projects/{project_id}/documents/{module}/ancestors/{node_kind}/{node_id}")
def ancestors(
    project_id: uuid.UUID,
    module: str,
    node_kind: str,
    node_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.ancestor_path(db, user, project_id, module, node_kind, node_id)


@router.post("/projects/{project_id}/documents/{module}", status_code=201)
def create_document(
    project_id: uuid.UUID,
    module: str,
    body: DocumentCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    if body.doc_type != module:
        from ..errors import invalid_request
        raise invalid_request("文档类型必须与当前模块一致")
    document = service.create_document(
        db, user, project_id, body.title, module, body.content, body.metadata, body.parent_id, body.directory_id
    )
    return service._document_dict(db, document)


@router.post("/projects/{project_id}/documents/{module}/directories", status_code=201)
def create_directory(
    project_id: uuid.UUID,
    module: str,
    body: DirectoryCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._directory_dict(db, service.create_directory(db, user, project_id, module, body.name, body.parent_id))


@router.get("/documents/{module}/{document_id}")
def get_document(
    module: str,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._document_dict(db, service.get_document(db, user, document_id, module))


@router.patch("/documents/{module}/{document_id}")
def update_document(
    module: str,
    document_id: uuid.UUID,
    body: DocumentUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module)
    metadata = body.metadata if "metadata" in body.model_fields_set else service._UNSET
    saved, warning = service.update_document(db, user, document.id, body.title, body.content, metadata)
    return service._document_dict(db, saved, warning)


@router.post("/documents/{module}/{document_id}/move")
def move_document(
    module: str,
    document_id: uuid.UUID,
    body: DocumentMove,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module)
    return service._document_dict(db, service.move_document(db, user, document.id, body.parent_id, body.directory_id))


@router.get("/documents/{module}/{document_id}/delete-impact")
def document_delete_impact(
    module: str,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module)
    return service.delete_impact_document(db, user, document.id)


@router.post("/documents/{module}/{document_id}/delete")
def delete_document(
    module: str,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module)
    service.delete_document(db, user, document.id)
    return {"ok": True}


@router.post("/documents/{module}/{document_id}/restore")
def restore_document(
    module: str,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service._visible_document(db, user, document_id, include_deleted=True)
    if document.doc_type != module:
        from ..errors import not_found
        raise not_found("文档不存在")
    return service._document_dict(db, service.restore_document(db, user, document.id))


@router.get("/documents/{module}/{document_id}/versions")
def list_versions(
    module: str,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": service.list_versions(db, user, document_id, module)}


@router.post("/documents/{module}/{document_id}/rollback")
def rollback_document(
    module: str,
    document_id: uuid.UUID,
    body: RollbackBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._document_dict(db, service.rollback_document(db, user, document_id, body.version_no, module))


@router.get("/documents/{module}/{document_id}/references")
def document_references(
    module: str,
    document_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.document_references(db, user, document_id, module)


@router.get("/directories/{module}/{directory_id}")
def get_directory(
    module: str,
    directory_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._directory_dict(db, service.get_directory(db, user, directory_id, module))


@router.patch("/directories/{module}/{directory_id}")
def rename_directory(
    module: str,
    directory_id: uuid.UUID,
    body: DirectoryRename,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    directory = service.get_directory(db, user, directory_id, module)
    return service._directory_dict(db, service.rename_directory(db, user, directory.id, body.name))


@router.post("/directories/{module}/{directory_id}/move")
def move_directory(
    module: str,
    directory_id: uuid.UUID,
    body: DirectoryMove,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    directory = service.get_directory(db, user, directory_id, module)
    return service._directory_dict(db, service.move_directory(db, user, directory.id, body.parent_id))


@router.get("/directories/{module}/{directory_id}/delete-impact")
def directory_delete_impact(
    module: str,
    directory_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    directory = service.get_directory(db, user, directory_id, module)
    return service.delete_impact_directory(db, user, directory.id)


@router.post("/directories/{module}/{directory_id}/delete")
def delete_directory(
    module: str,
    directory_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    directory = service.get_directory(db, user, directory_id, module)
    service.delete_directory(db, user, directory.id)
    return {"ok": True}


@router.post("/directories/{module}/{directory_id}/restore")
def restore_directory(
    module: str,
    directory_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    directory = service._get_directory_raw(db, directory_id)
    if directory.module_type != module:
        from ..errors import not_found
        raise not_found("目录不存在")
    return service._directory_dict(db, service.restore_directory(db, user, directory.id))
