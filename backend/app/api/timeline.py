"""Web adapter for the project-scoped requirement timeline."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..v2 import timeline as service
from ..v2.resource_refs import ResourceKind, ResourceRef, parse_uuid
from .deps import current_user
from .v2_transport import V2Route, commit_command


router = APIRouter(
    prefix="/api/projects/{project_id}/requirements/{requirement_id}/timeline",
    tags=["requirement timeline"],
    route_class=V2Route,
)


class AppendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    body: str
    reply_to: str | None = None
    source_task: str | None = None


class ChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    expected_version: StrictInt
    reason: str | None = None


class ReviseBody(ChangeBody):
    body: str


def _scope(project_id: str, requirement_id: str) -> ResourceRef:
    return ResourceRef(parse_uuid(project_id, "project_id"), ResourceKind.REQUIREMENT, requirement_id)


@router.get("")
def list_timeline(
    project_id: str, requirement_id: str, cursor: str | None = None, limit: int = 20,
    kind: str | None = None, actor_id: str | None = None, source_task: str | None = None,
    keyword: str | None = None, from_at: datetime | None = None, to_at: datetime | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.list_entries(
        db, user, _scope(project_id, requirement_id), cursor=cursor, limit=limit,
        kind=kind, actor_id=parse_uuid(actor_id, "actor_id") if actor_id is not None else None,
        source_task=source_task, keyword=keyword, from_at=from_at, to_at=to_at,
    )


@router.post("", status_code=201)
def append_timeline(
    project_id: str, requirement_id: str, body: AppendBody,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return commit_command(db, lambda: service.append_entry(
        db, user, _scope(project_id, requirement_id),
        request_id=parse_uuid(body.request_id, "request_id"), body=body.body, source_task=body.source_task,
        reply_to=parse_uuid(body.reply_to, "reply_to") if body.reply_to is not None else None,
    ))


@router.get("/{entry_id}")
def get_timeline_entry(
    project_id: str, requirement_id: str, entry_id: str,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.get_entry(db, user, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"))


@router.get("/{entry_id}/context")
def get_timeline_context(
    project_id: str, requirement_id: str, entry_id: str, radius: int = 10,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.get_context(
        db, user, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"), radius=radius,
    )


@router.patch("/{entry_id}")
def revise_timeline_entry(
    project_id: str, requirement_id: str, entry_id: str, body: ReviseBody,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return commit_command(db, lambda: service.revise_entry(
        db, user, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"),
        request_id=parse_uuid(body.request_id, "request_id"), expected_version=body.expected_version,
        body=body.body, reason=body.reason,
    ))


@router.post("/{entry_id}/withdraw")
def withdraw_timeline_entry(
    project_id: str, requirement_id: str, entry_id: str, body: ChangeBody,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return commit_command(db, lambda: service.withdraw_entry(
        db, user, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"),
        request_id=parse_uuid(body.request_id, "request_id"),
        expected_version=body.expected_version, reason=body.reason,
    ))


@router.get("/{entry_id}/revisions")
def list_timeline_revisions(
    project_id: str, requirement_id: str, entry_id: str, cursor: str | None = None, limit: int = 20,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.list_revisions(
        db, user, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"),
        cursor=cursor, limit=limit,
    )


@router.get("/{entry_id}/revisions/{version}")
def get_timeline_revision(
    project_id: str, requirement_id: str, entry_id: str, version: int,
    user: User = Depends(current_user), db: Session = Depends(get_db),
) -> dict:
    return service.get_revision(db, user, _scope(project_id, requirement_id), parse_uuid(entry_id, "entry_id"), version)
