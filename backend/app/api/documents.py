"""Wiki 文档工作台 HTTP API(REQ-59:glossary 合并进 wiki,单模块)。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import DocumentCreate, DocumentMove, DocumentUpdate, RollbackBody
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
    parent_id: str | None = None,
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
    node_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.ancestor_path(db, user, project_id, module, node_kind, node_id)


@router.get("/projects/{project_id}/documents/index")
def project_index(
    project_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    """项目知识 INDEX(后端投影,kind 分节+未分类兜底+lint 信号)。"""
    return service.project_index(db, user, project_id)


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
    document, link_warning = service.create_document(
        db, user, project_id, body.title, module, body.content, body.metadata, body.parent_id
    )
    return service._document_dict(db, document, warning=link_warning, with_links=True)


@router.get("/documents/{module}/{document_id}")
def get_document(
    module: str,
    document_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service._document_dict(
        db,
        service.get_document(db, user, document_id, module, project_id=project_id),
        with_links=True,
    )


@router.patch("/documents/{module}/{document_id}")
def update_document(
    module: str,
    document_id: str,
    body: DocumentUpdate,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module, project_id=project_id)
    metadata = body.metadata if "metadata" in body.model_fields_set else service._UNSET
    saved, link_warning = service.update_document(
        db, user, document.code, body.title, body.content, metadata, project_id=project_id
    )
    return service._document_dict(db, saved, warning=link_warning, with_links=True)


@router.post("/documents/{module}/{document_id}/move")
def move_document(
    module: str,
    document_id: str,
    body: DocumentMove,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module, project_id=project_id)
    return service._document_dict(
        db,
        service.move_document(
            db, user, document.code, body.parent_id, project_id=project_id
        ),
    )


@router.get("/documents/{module}/{document_id}/delete-impact")
def document_delete_impact(
    module: str,
    document_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module, project_id=project_id)
    return service.delete_impact_document(db, user, document.code, project_id=project_id)


@router.post("/documents/{module}/{document_id}/delete")
def delete_document(
    module: str,
    document_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service.get_document(db, user, document_id, module, project_id=project_id)
    service.delete_document(db, user, document.code, project_id=project_id)
    return {"ok": True}


@router.post("/documents/{module}/{document_id}/restore")
def restore_document(
    module: str,
    document_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    document = service._visible_document(
        db, user, document_id, include_deleted=True, project_id=project_id
    )
    if document.doc_type != module:
        from ..errors import not_found
        raise not_found("文档不存在")
    return service._document_dict(
        db, service.restore_document(db, user, document.code, project_id=project_id)
    )


@router.get("/documents/{module}/{document_id}/versions")
def list_versions(
    module: str,
    document_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": service.list_versions(db, user, document_id, module, project_id=project_id)}


@router.post("/documents/{module}/{document_id}/rollback")
def rollback_document(
    module: str,
    document_id: str,
    body: RollbackBody,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    saved, link_warning = service.rollback_document(
        db, user, document_id, body.version_no, module, project_id=project_id
    )
    return service._document_dict(db, saved, warning=link_warning, with_links=True)


@router.get("/documents/{module}/{document_id}/references")
def document_references(
    module: str,
    document_id: str,
    project_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return service.document_references(db, user, document_id, module, project_id=project_id)
