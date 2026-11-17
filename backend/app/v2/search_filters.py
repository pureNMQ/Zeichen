"""Filters shared by the project search transports."""

from datetime import UTC
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session

from ..errors import invalid_request
from ..models import Requirement, Task
from ..models.requirement import REQUIREMENT_STATUS_VALUES
from .file_models import FileAssociation, ProjectFile
from .resource_refs import ResourceKind, ResourceRef, parse_uuid
from .wiki_models import Wiki, WikiReference, visible_wiki_tree


FilterText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_status: Literal[*REQUIREMENT_STATUS_VALUES] | None = None
    timeline_actor_id: UUID | None = None
    timeline_kind: Literal["manual", "system"] | None = None
    timeline_source_task: FilterText | None = None
    wiki_category: FilterText | None = None
    wiki_tag: FilterText | None = None
    file_media_type: FilterText | None = None
    file_uploader_id: UUID | None = None
    file_used_at: FilterText | None = None
    from_at: AwareDatetime | None = None
    to_at: AwareDatetime | None = None

    def validate_range(self) -> None:
        if self.from_at is not None and self.to_at is not None and self.from_at >= self.to_at:
            raise invalid_request("结束时间须晚于开始时间")

    def time_predicates(self, column) -> list:
        predicates = []
        if self.from_at is not None:
            predicates.append(column >= self.from_at.astimezone(UTC))
        if self.to_at is not None:
            predicates.append(column < self.to_at.astimezone(UTC))
        return predicates


def _by_field(model, field, project_id: UUID, target_id: str, active):
    return select(field).where(model.project_id == project_id, field == target_id, active).exists()


def file_used_at_predicate(href: str, project_ids: tuple[UUID, ...]):
    """Match live explicit associations or the current visible Wiki snapshot."""
    try:
        parts = urlsplit(href)
    except ValueError as exc:
        raise invalid_request("使用位置须为站内项目资源链接") from exc
    if parts.scheme or parts.netloc or parts.query or parts.fragment or href != parts.path:
        raise invalid_request("使用位置须为站内项目、需求、任务或 Wiki 链接")
    if parts.path.startswith("/projects/") and parts.path.count("/") == 2:
        project_id = parse_uuid(parts.path.split("/")[-1], "file_used_at.project_id")
        kind, target_id = "project", str(project_id)
    else:
        target = ResourceRef.from_markdown_href(href)
        if target is None or target.kind not in {ResourceKind.REQUIREMENT, ResourceKind.TASK, ResourceKind.WIKI}:
            raise invalid_request("使用位置须为站内项目、需求、任务或 Wiki 链接")
        project_id, kind, target_id = target.project_id, target.kind.value, target.identifier
    if project_id not in project_ids:
        raise invalid_request("使用位置必须属于已选择的检索项目")

    explicit_use = select(FileAssociation.file_id).where(
        FileAssociation.project_id == project_id, FileAssociation.file_id == ProjectFile.id,
        FileAssociation.target_kind == kind, FileAssociation.target_id == target_id,
    ).exists()
    in_project = ProjectFile.project_id == project_id
    if kind == ResourceKind.REQUIREMENT:
        visible = _by_field(Requirement, Requirement.code, project_id, target_id, Requirement.deleted_at.is_(None))
    elif kind == ResourceKind.TASK:
        visible = _by_field(Task, Task.code, project_id, target_id, and_(Task.deleted_at.is_(None), Task.has_active_requirement()))
    elif kind == ResourceKind.WIKI:
        tree = visible_wiki_tree(project_id)
        visible = select(tree.c.code).where(tree.c.code == target_id).exists()
        wiki_use = select(WikiReference.target_id).join(Wiki, and_(
            Wiki.project_id == WikiReference.project_id, Wiki.code == WikiReference.wiki_code,
            Wiki.version_no == WikiReference.version_no,
        )).where(
            WikiReference.project_id == project_id, WikiReference.wiki_code == target_id,
            WikiReference.target_kind == ResourceKind.FILE.value,
            func.replace(WikiReference.target_id, "-", "") == func.replace(cast(ProjectFile.id, String), "-", ""),
        ).correlate(ProjectFile).exists()
        return and_(in_project, visible, or_(explicit_use, wiki_use))
    else:
        return and_(in_project, explicit_use)
    return and_(in_project, visible, explicit_use)


def wiki_tag_predicate(db: Session, tag: str):
    json_values = (
        func.json_array_elements_text(Wiki.tags).table_valued("value").render_derived()
        if db.get_bind().dialect.name == "postgresql"
        else func.json_each(Wiki.tags).table_valued("value")
    )
    return select(json_values.c.value).where(json_values.c.value == tag).correlate(Wiki).exists()
