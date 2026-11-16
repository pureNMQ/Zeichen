"""Import legacy history from the cloned v1 database into v2 timeline tables."""

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Activity, Comment, Requirement, Task
from .timeline_models import TimelineEntry, TimelineRevision


@dataclass(frozen=True)
class ImportException:
    source: str
    source_id: str
    project_id: str
    target_id: str
    reason: str


def import_timeline(db: Session) -> tuple[dict[str, int], list[ImportException]]:
    """Run on the stopped clone; never update the legacy rows or send notifications."""
    counts: Counter[str] = Counter()
    exceptions: list[ImportException] = []

    def exception(source: str, row: Activity | Comment, reason: str) -> None:
        exceptions.append(ImportException(source, str(row.id), str(row.project_id), row.target_id, reason))

    def write(entry: TimelineEntry, source: Activity | Comment) -> bool:
        existing = db.get(TimelineEntry, source.id)
        if existing is not None:
            if (existing.project_id, existing.requirement_code, existing.kind) != (
                entry.project_id, entry.requirement_code, entry.kind,
            ):
                raise RuntimeError(f"Legacy timeline identity collision: {source.id}")
            counts["already_imported"] += 1
            return False
        db.add(entry)
        db.flush()
        return True

    for comment in db.scalars(select(Comment).order_by(Comment.created_at, Comment.id)).yield_per(250):
        if comment.target_type != "requirement":
            counts["comments_retained_in_legacy_history"] += 1
            continue
        if db.get(Requirement, (comment.project_id, comment.target_id)) is None:
            exception("comment", comment, "requirement_missing")
            continue
        entry = TimelineEntry(
            id=comment.id, project_id=comment.project_id, requirement_code=comment.target_id,
            kind="manual", occurred_at=comment.created_at, actor_id=comment.author_id,
            latest_version=2 if comment.deleted_at is not None else 1,
        )
        if not write(entry, comment):
            continue
        db.add(TimelineRevision(
            project_id=comment.project_id, requirement_code=comment.target_id, entry_id=comment.id,
            version=1, kind="create", body=comment.body, actor_id=comment.author_id,
            created_at=comment.created_at,
        ))
        if comment.deleted_at is not None:
            db.add(TimelineRevision(
                project_id=comment.project_id, requirement_code=comment.target_id, entry_id=comment.id,
                version=2, kind="withdraw", created_at=comment.deleted_at,
                reason="旧版评论已删除，操作人未记录",
            ))
        counts["comments_imported"] += 1

    reparented = {
        (row.project_id, row.target_id)
        for row in db.execute(select(Activity.project_id, Activity.target_id).where(
            Activity.target_type == "task", Activity.action == "update", Activity.summary == "关联需求",
        ))
    }
    for activity in db.scalars(select(Activity).order_by(Activity.created_at, Activity.id)).yield_per(250):
        code = activity.target_id
        task_code = None
        if activity.target_type == "task":
            if (activity.project_id, code) in reparented:
                exception("activity", activity, "task_requirement_at_event_unknown")
                continue
            task = db.get(Task, (activity.project_id, code))
            if task is None:
                exception("activity", activity, "task_missing")
                continue
            task_code, code = code, task.requirement_id
        elif activity.target_type != "requirement":
            counts["activity_retained_in_legacy_history"] += 1
            continue
        if db.get(Requirement, (activity.project_id, code)) is None:
            exception("activity", activity, "requirement_missing")
            continue
        entry = TimelineEntry(
            id=activity.id, project_id=activity.project_id, requirement_code=code,
            kind="system", occurred_at=activity.created_at, actor_id=activity.actor_id,
            source_task_code=task_code, event_type="legacy.activity",
            event_data={"action": activity.action, "summary": activity.summary},
        )
        if write(entry, activity):
            counts["activity_imported"] += 1
    db.flush()
    return dict(counts), exceptions
