"""Convert the retired independent links into versioned project Markdown."""
from datetime import UTC, datetime
from itertools import groupby
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Document, Project, Reference, Repository, Requirement, Task, User
from ..services.short_codes import allocate_code
from .markdown_refs import extract_markdown_refs
from .resource_refs import ResourceKind, ResourceRef
from .wiki import WikiContent, _record_snapshot
from .wiki_models import Wiki, WikiVersion
from .work_content import snapshot
from .work_content_models import WorkReference, WorkVersion

_KINDS = {"requirement": ResourceKind.REQUIREMENT, "task": ResourceKind.TASK, "document": ResourceKind.WIKI}
_RELATIONS = {"mentions": "提及", "derives": "派生", "documents": "记录", "implements": "实现"}


def _endpoint(db, project, kind, identifier):
    if kind == "task":
        item = db.scalar(select(Task).where(Task.project_id == project, Task.matches_code(identifier)))
    elif kind in ("requirement", "document"):
        item = db.get(Requirement if kind == "requirement" else Wiki, (project, identifier))
    else:
        try:
            key = UUID(identifier)
        except ValueError:
            return None
        if kind == "project" and key == project and db.get(Project, key):
            return None, f"[项目](/projects/{project})"
        if kind == "repository":
            repo = db.get(Repository, key)
            if repo and repo.project_id == project:
                return None, f"[代码仓库 {key}](/projects/{project}/repositories#repository-{key})"
        if kind == "user" and db.get(User, key):
            ref = ResourceRef(project, ResourceKind.PERSON, str(key))
            return None, f"[成员 {key}]({ref.path})"
        return None
    if item is None:
        return None
    ref = ResourceRef(project, _KINDS[kind], item.code)
    return item, f"[{item.code}]({ref.path})"


def _already_removed(db, item, target, edge):
    if not isinstance(item, (Requirement, Task)) or target is None:
        return False
    last = db.scalar(select(func.max(WorkReference.version)).where(
        WorkReference.project_id == item.project_id, WorkReference.code == item.code,
        WorkReference.target_kind == target.kind.value, WorkReference.target_id == target.identifier))
    if last is None or last >= item.version:
        return False
    removed = db.get(WorkVersion, (item.project_id, item.code, last + 1))
    return removed is not None and edge.created_at.replace(tzinfo=UTC) <= removed.created_at.replace(tzinfo=UTC)


def _new_archive(db, project, kind, identifier):
    # Some clone imports bring legacy Wiki documents in after Alembic runs.
    code = allocate_code(db, project, "document")
    while db.get(Wiki, (project, code)) or db.get(Document, (project, code)):
        code = allocate_code(db, project, "document")
    wiki = Wiki(project_id=project, code=code, title=f"历史引用 · {kind} {identifier}", body="", tags=[], version_no=1)
    db.add(wiki)
    db.flush()
    return wiki


def migrate_references(db: Session):
    counts = {"archived": 0, "updated_bodies": 0}
    exceptions = []
    edges = db.scalars(select(Reference).where(Reference.deleted_at.is_(None)).order_by(
        Reference.project_id, Reference.from_type, Reference.from_id, Reference.created_at, Reference.id))
    for (project, kind, identifier), group in groupby(edges, lambda r: (r.project_id, r.from_type, r.from_id)):
        source = _endpoint(db, project, kind, identifier)
        additions = []
        item = source[0] if source else None
        archive_id = uuid5(project, f"legacy-reference-archive/{kind}/{identifier}")
        archive_version = db.get(WikiVersion, archive_id) if source and item is None else None
        if archive_version:
            item = db.get(Wiki, (project, archive_version.wiki_code))
        body = getattr(item, "body", None) or getattr(item, "description", None) or ""
        existing = extract_markdown_refs(body, project)
        for edge in group:
            target = _endpoint(db, project, edge.to_type, edge.to_id)
            if not source or not target:
                exceptions.append({"reference_id": str(edge.id), "reason": "unresolved_source_or_target"})
                continue
            # v2workcontent already folded these links into the first work revision.
            # Respect a subsequent edit that deliberately removed one of them.
            ref = (ResourceRef(project, _KINDS[edge.to_type], target[0].code)
                   if target[0] is not None else None)
            if ref not in existing and not _already_removed(db, item, ref, edge):
                relation = _RELATIONS.get(edge.type, edge.type)
                prefix = source[1] + " " if source[0] is None else ""
                additions.append(f"- {prefix}{relation} {target[1]}")
            edge.deleted_at = datetime.now(UTC)
            counts["archived"] += 1
        if not additions:
            continue
        section = "## 相关引用\n\n" + "\n".join(dict.fromkeys(additions))
        combined = body + "\n\n" + section if body else section
        # An unfinished fence or HTML block at EOF can swallow an appended Markdown section.
        needed = extract_markdown_refs(section, project)
        if not needed.issubset(extract_markdown_refs(combined, project)):
            combined = section + "\n\n" + body
        body = combined
        if item is None:
            item = _new_archive(db, project, kind, identifier)
            item.body = body
        elif isinstance(item, Wiki):
            item.body = body
            item.version_no += 1
        else:
            item.description = body
            item.version += 1
        if isinstance(item, Wiki):
            _record_snapshot(db, None, project, item.code, item.version_no, WikiContent.model_validate(item),
                             snapshot_id=archive_id if source[0] is None and archive_version is None else None)
        else:
            snapshot(db, item, None)
        counts["updated_bodies"] += 1
    db.flush()
    return counts, exceptions
