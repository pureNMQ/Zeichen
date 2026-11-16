"""Project-scoped Wiki reads and transactional commands shared by Web and MCP."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import and_, select, tuple_, update
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..services.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from ..services.permissions import get_accessible_project, require_project_role
from ..services.short_codes import allocate_code
from .commands import execute_once
from .markdown_refs import extract_markdown_refs
from .resource_refs import ResourceKind, ResourceRef
from .wiki_models import Wiki, WikiReference, WikiVersion

WikiTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
WikiTag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WikiContent(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    title: WikiTitle
    body: str = ""
    summary: str | None = None
    category: str | None = None
    tags: list[WikiTag] = Field(default_factory=list)


class WikiPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: WikiTitle | None = None
    body: str | None = None
    summary: str | None = None
    category: str | None = None
    tags: list[WikiTag] | None = None


def _active_wiki(db: Session, project_id: UUID, code: str) -> Wiki:
    ResourceRef(project_id, ResourceKind.WIKI, code)
    wiki = db.scalar(
        select(Wiki)
        .where(Wiki.project_id == project_id, Wiki.code == code, Wiki.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    )
    if wiki is None:
        raise not_found("Wiki 不存在")
    return wiki


def read_wiki(db: Session, actor_id: UUID, project_id: UUID, code: str) -> Wiki:
    get_accessible_project(db, actor_id, project_id)
    return _active_wiki(db, project_id, code)


def _version(db: Session, project_id: UUID, code: str, version_no: int) -> WikiVersion:
    if version_no < 1:
        raise invalid_request("版本号必须大于零")
    version = db.scalar(select(WikiVersion).where(
        WikiVersion.project_id == project_id,
        WikiVersion.wiki_code == code,
        WikiVersion.version_no == version_no,
    ))
    if version is None:
        raise not_found("Wiki 版本不存在")
    return version


def read_version(db: Session, actor_id: UUID, project_id: UUID, code: str, version_no: int) -> WikiVersion:
    read_wiki(db, actor_id, project_id, code)
    return _version(db, project_id, code, version_no)


def store_version_references(db: Session, version: WikiVersion) -> None:
    """Index a newly inserted snapshot; also used by replayable legacy importers."""
    refs = extract_markdown_refs(version.body, version.project_id)
    db.add_all([
        WikiReference(
            project_id=version.project_id,
            wiki_code=version.wiki_code,
            version_no=version.version_no,
            target_kind=ref.kind.value,
            target_id=ref.identifier,
        )
        for ref in sorted(refs, key=lambda target: (target.kind, target.identifier))
    ])


def _record_snapshot(
    db: Session, actor_id: UUID, project_id: UUID, code: str, version_no: int, content: WikiContent,
) -> None:
    version = WikiVersion(
        project_id=project_id, wiki_code=code, version_no=version_no,
        created_by=actor_id, **content.model_dump(),
    )
    db.add(version)
    db.flush()
    store_version_references(db, version)
    db.flush()


def _receipt(project_id: UUID, code: str, version: int) -> dict:
    return {"project_id": str(project_id), "id": code, "version": version}


def create_wiki(
    db: Session, actor_id: UUID, project_id: UUID, *, request_id: UUID,
    content: WikiContent, parent_id: str | None = None,
) -> dict:
    require_project_role(db, actor_id, project_id)

    def apply() -> dict:
        if parent_id is not None:
            _active_wiki(db, project_id, parent_id)
        code = allocate_code(db, project_id, "document")
        wiki = Wiki(
            project_id=project_id, code=code, created_by=actor_id,
            parent_id=parent_id, version_no=1, **content.model_dump(),
        )
        db.add(wiki)
        db.flush()
        _record_snapshot(db, actor_id, project_id, code, 1, content)
        return _receipt(project_id, code, 1)

    return execute_once(
        db, project_id=project_id, actor_id=actor_id, operation="wiki.create", request_id=request_id,
        payload={"parent_id": parent_id, **content.model_dump(mode="json")}, apply=apply,
    )


def _replace(
    db: Session, actor_id: UUID, wiki: Wiki, expected_version: int, content: WikiContent,
) -> dict:
    if expected_version < 1:
        raise invalid_request("expected_version 必须大于零")
    if wiki.version_no != expected_version:
        raise conflict(f"Wiki 已更新，当前版本为 {wiki.version_no}，请重新读取后再保存")
    project_id, code = wiki.project_id, wiki.code
    next_version = expected_version + 1
    saved_code = db.scalar(
        update(Wiki)
        .where(
            Wiki.project_id == project_id, Wiki.code == code,
            Wiki.version_no == expected_version, Wiki.deleted_at.is_(None),
        )
        .values(version_no=next_version, **content.model_dump())
        .returning(Wiki.code)
        .execution_options(synchronize_session=False)
    )
    if saved_code is None:
        raise conflict("Wiki 在保存期间已更新或删除，请重新读取")
    db.expire(wiki)
    _record_snapshot(db, actor_id, project_id, code, next_version, content)
    return _receipt(project_id, code, next_version)


def update_wiki(
    db: Session, actor_id: UUID, project_id: UUID, code: str, *,
    expected_version: int, patch: WikiPatch,
) -> dict:
    require_project_role(db, actor_id, project_id)
    wiki = _active_wiki(db, project_id, code)
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise invalid_request("至少指定一个要保存的字段")
    for field in ("title", "body", "tags"):
        if field in fields and fields[field] is None:
            raise invalid_request(f"{field} 不接受 null")
    content = WikiContent.model_validate(wiki).model_copy(update=fields)
    return _replace(db, actor_id, wiki, expected_version, content)


def restore_wiki_version(
    db: Session, actor_id: UUID, project_id: UUID, code: str, *,
    expected_version: int, from_version: int,
) -> dict:
    require_project_role(db, actor_id, project_id)
    wiki = _active_wiki(db, project_id, code)
    previous = _version(db, project_id, code, from_version)
    return _replace(db, actor_id, wiki, expected_version, WikiContent.model_validate(previous))


def read_references(
    db: Session, actor_id: UUID, project_id: UUID, code: str, *, version_no: int | None = None,
) -> list[ResourceRef]:
    wiki = read_wiki(db, actor_id, project_id, code)
    if version_no is None:
        version_no = wiki.version_no
    else:
        _version(db, project_id, code, version_no)
    refs = db.scalars(select(WikiReference).where(
        WikiReference.project_id == project_id, WikiReference.wiki_code == code,
        WikiReference.version_no == version_no,
    ).order_by(WikiReference.target_kind, WikiReference.target_id))
    return [ResourceRef(project_id, ResourceKind(ref.target_kind), ref.target_id) for ref in refs]


@dataclass(frozen=True, slots=True)
class WikiReferenceUse:
    wiki_code: str
    version_no: int
    current: bool


def find_reference_uses(
    db: Session, actor_id: UUID, target: ResourceRef, *, include_history: bool = False,
    after: tuple[str, int] | None = None, limit: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[WikiReferenceUse], tuple[str, int] | None]:
    """Read project-scoped backlinks. Transport binds the keyset to its query scope."""
    get_accessible_project(db, actor_id, target.project_id)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise invalid_request(f"limit 必须在 1..{MAX_PAGE_SIZE} 之间")
    current = WikiReference.version_no == Wiki.version_no
    statement = select(WikiReference.wiki_code, WikiReference.version_no, current).join(
        Wiki, and_(WikiReference.project_id == Wiki.project_id, WikiReference.wiki_code == Wiki.code),
    ).where(
        WikiReference.project_id == target.project_id, WikiReference.target_kind == target.kind.value,
        WikiReference.target_id == target.identifier, Wiki.deleted_at.is_(None),
    )
    if not include_history:
        statement = statement.where(current)
    if after is not None:
        statement = statement.where(tuple_(WikiReference.wiki_code, WikiReference.version_no) > after)
    rows = db.execute(statement.order_by(WikiReference.wiki_code, WikiReference.version_no).limit(limit + 1)).all()
    page = [WikiReferenceUse(code, version, active) for code, version, active in rows[:limit]]
    next_key = (page[-1].wiki_code, page[-1].version_no) if len(rows) > limit else None
    return page, next_key
