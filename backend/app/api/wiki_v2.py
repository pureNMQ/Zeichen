"""HTTP adapter for the structured Wiki."""

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import invalid_request
from ..models import User
from ..services.pagination import decode_cursor, encode_cursor
from ..services.permissions import get_accessible_project, require_project_role
from ..v2 import wiki as service
from ..v2.resource_refs import parse_uuid
from ..v2.wiki_models import Wiki, WikiVersion
from .deps import current_user


class WikiRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handle(request)
            except RequestValidationError as error:
                fields = {str(issue["loc"][-1])[:64] for issue in error.errors()[:8] if issue.get("loc")}
                raise invalid_request(f"Wiki 参数无效：{', '.join(sorted(fields))}") from error

        return validated


router = APIRouter(
    prefix="/api/v2/projects/{project_id}/wiki", tags=["structured Wiki"], route_class=WikiRoute,
)


class WikiCreate(service.WikiContent):
    request_id: str
    parent_id: str | None = None


class WikiUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: StrictInt
    patch: service.WikiPatch


class WikiRestoreVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: StrictInt


class WikiMove(WikiRestoreVersion):
    parent_id: str | None


def _summary(wiki: Wiki) -> dict:
    return {
        "id": wiki.code, "project_id": str(wiki.project_id), "parent_id": wiki.parent_id,
        "version": wiki.version_no, "title": wiki.title, "summary": wiki.summary,
        "category": wiki.category, "tags": wiki.tags, "created_at": wiki.created_at,
        "updated_at": wiki.updated_at,
    }


@router.get("")
def list_documents(
    project_id: str, q: str = "", cursor: str | None = None, limit: int = 20,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    scope = parse_uuid(project_id, "project_id")
    get_accessible_project(db, user.id, scope)
    q = q.strip()
    if not 1 <= limit <= 100 or len(q) > 256:
        raise invalid_request("Wiki 每页 1 到 100 项，查询最多 256 字")
    filters = {"project_id": project_id, "kind": "wiki", "q": q}
    offset = decode_cursor(filters, cursor)
    stmt = select(Wiki).where(Wiki.project_id == scope, Wiki.code.in_(service.visible_wiki_codes(scope)))
    if q:
        stmt = stmt.where(Wiki.title.icontains(q, autoescape=True))
    wikis = list(db.scalars(stmt.order_by(Wiki.code).offset(offset).limit(limit + 1)))
    return {
        "items": [_summary(wiki) for wiki in wikis[:limit]],
        "next_cursor": encode_cursor(filters, offset + limit, limit) if len(wikis) > limit else None,
    }


@router.post("", status_code=201)
def create_document(
    project_id: str, body: WikiCreate, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    receipt = service.create_wiki(
        db, user.id, parse_uuid(project_id, "project_id"), request_id=parse_uuid(body.request_id, "request_id"),
        parent_id=body.parent_id,
        content=service.WikiContent.model_validate(body.model_dump(exclude={"request_id", "parent_id"})),
    )
    db.commit()
    return receipt


@router.get("/trash")
def list_deleted_wikis(
    project_id: str, q: str = "", cursor: str | None = None, limit: int = 20,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    scope = parse_uuid(project_id, "project_id")
    require_project_role(db, user.id, scope, min_level="editor")
    q = q.strip()
    if not 1 <= limit <= 100 or len(q) > 256:
        raise invalid_request("回收站每页 1 到 100 项，查询最多 256 字")
    filters = {"project_id": project_id, "kind": "wiki_trash", "q": q}
    offset = decode_cursor(filters, cursor)
    stmt = select(Wiki).where(Wiki.project_id == scope, Wiki.deleted_at.is_not(None))
    if q:
        stmt = stmt.where(Wiki.title.icontains(q, autoescape=True) | Wiki.code.icontains(q, autoescape=True))
    rows = list(db.scalars(stmt.order_by(Wiki.deleted_at.desc(), Wiki.code).offset(offset).limit(limit + 1)))
    return {
        "items": [{**_summary(row), "deleted_at": row.deleted_at, "deleted_by": row.deleted_by}
                  for row in rows[:limit]],
        "next_cursor": encode_cursor(filters, offset + limit, limit) if len(rows) > limit else None,
    }


@router.get("/trash/{code}")
def get_deleted_wiki(
    project_id: str, code: str, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    scope = parse_uuid(project_id, "project_id")
    wiki = service.read_deleted_wiki(db, user.id, scope, code)
    return {**_summary(wiki), "deleted_at": wiki.deleted_at, "deleted_by": wiki.deleted_by, "body": wiki.body}


@router.post("/trash/{code}/restore")
def restore_document(
    project_id: str, code: str, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    receipt = service.restore_wiki(db, user.id, parse_uuid(project_id, "project_id"), code)
    db.commit()
    return receipt


@router.get("/{code}")
def get_document(
    project_id: str, code: str, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    wiki = service.read_wiki(db, user.id, parse_uuid(project_id, "project_id"), code)
    return {**_summary(wiki), "body": wiki.body}


@router.patch("/{code}")
def update_document(
    project_id: str, code: str, body: WikiUpdate, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    receipt = service.update_wiki(
        db, user.id, parse_uuid(project_id, "project_id"), code,
        expected_version=body.expected_version, patch=body.patch,
    )
    db.commit()
    return receipt


@router.patch("/{code}/location")
def move_document(
    project_id: str, code: str, body: WikiMove,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    receipt = service.move_wiki(
        db, user.id, parse_uuid(project_id, "project_id"), code, body.parent_id, body.expected_version,
    )
    db.commit()
    return receipt


@router.get("/{code}/delete-impact")
def get_delete_impact(
    project_id: str, code: str, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.wiki_delete_impact(db, user.id, parse_uuid(project_id, "project_id"), code)


@router.delete("/{code}")
def delete_document(
    project_id: str, code: str, confirmed_count: int,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    receipt = service.delete_wiki(db, user.id, parse_uuid(project_id, "project_id"), code, confirmed_count)
    db.commit()
    return receipt


@router.get("/{code}/versions")
def list_versions(
    project_id: str, code: str, before: int | None = None, limit: int = 20,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    scope = parse_uuid(project_id, "project_id")
    service.read_wiki(db, user.id, scope, code)
    if not 1 <= limit <= 100 or (before is not None and before < 1):
        raise invalid_request("版本页参数无效")
    stmt = select(WikiVersion.version_no, WikiVersion.title, WikiVersion.created_by, WikiVersion.created_at).where(
        WikiVersion.project_id == scope, WikiVersion.wiki_code == code,
    )
    if before is not None:
        stmt = stmt.where(WikiVersion.version_no < before)
    rows = db.execute(stmt.order_by(WikiVersion.version_no.desc()).limit(limit + 1)).all()
    return {
        "items": [{"version": row.version_no, "title": row.title, "created_by": row.created_by,
                   "created_at": row.created_at} for row in rows[:limit]],
        "next_before": rows[limit - 1].version_no if len(rows) > limit else None,
    }


@router.get("/{code}/versions/{version_no}")
def get_version(
    project_id: str, code: str, version_no: int, user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    version = service.read_version(db, user.id, parse_uuid(project_id, "project_id"), code, version_no)
    return {"id": code, "project_id": project_id, "version": version_no,
            **service.WikiContent.model_validate(version).model_dump()}


@router.post("/{code}/versions/{version_no}/restore")
def restore_version(
    project_id: str, code: str, version_no: int, body: WikiRestoreVersion,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    receipt = service.restore_wiki_version(
        db, user.id, parse_uuid(project_id, "project_id"), code,
        expected_version=body.expected_version, from_version=version_no,
    )
    db.commit()
    return receipt
