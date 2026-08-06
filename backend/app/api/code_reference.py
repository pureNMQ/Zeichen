"""HTTP API for the independent code API reference."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import CodeLibraryCreate, CodeSymbolCreate, CodeSymbolRollback, CodeSymbolUpdate
from ..services import code_reference as service
from .deps import current_user

router = APIRouter(prefix="/api", tags=["code-reference"])


@router.get("/projects/{project_id}/code-reference/libraries")
def list_libraries(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_libraries(db, user, project_id)}


@router.post("/projects/{project_id}/code-reference/libraries", status_code=201)
def create_library(project_id: uuid.UUID, body: CodeLibraryCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._library_dict(service.create_library(db, user, project_id, body.name, body.language, body.package, body.version))


@router.get("/projects/{project_id}/code-reference/tree")
def code_tree(project_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.code_tree(db, user, project_id)


@router.get("/projects/{project_id}/code-reference/search")
def search_symbols(
    project_id: uuid.UUID,
    q: str | None = Query(default=None, max_length=256),
    library_id: uuid.UUID | None = None,
    kind: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"items": service.search_symbols(db, user, project_id, q, library_id, kind)}


@router.post("/code-reference/libraries/{library_id}/symbols", status_code=201)
def create_symbol(library_id: uuid.UUID, body: CodeSymbolCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._symbol_dict(service.create_symbol(db, user, library_id, body.model_dump()))


@router.get("/code-reference/symbols/{symbol_id}")
def get_symbol(symbol_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service.get_symbol(db, user, symbol_id)


@router.patch("/code-reference/symbols/{symbol_id}")
def update_symbol(symbol_id: uuid.UUID, body: CodeSymbolUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    patch = body.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    return service._symbol_dict(service.update_symbol(db, user, symbol_id, body.expected_revision, patch))


@router.get("/code-reference/symbols/{symbol_id}/members")
def list_members(symbol_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_members(db, user, symbol_id)}


@router.get("/code-reference/symbols/{symbol_id}/versions")
def list_versions(symbol_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return {"items": service.list_versions(db, user, symbol_id)}


@router.post("/code-reference/symbols/{symbol_id}/rollback")
def rollback_symbol(symbol_id: uuid.UUID, body: CodeSymbolRollback, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._symbol_dict(service.rollback_symbol(db, user, symbol_id, body.revision, body.expected_revision))


@router.post("/code-reference/symbols/{symbol_id}/delete")
def delete_symbol(symbol_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    service.delete_symbol(db, user, symbol_id)
    return {"ok": True}


@router.post("/code-reference/symbols/{symbol_id}/restore")
def restore_symbol(symbol_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    return service._symbol_dict(service.restore_symbol(db, user, symbol_id))
