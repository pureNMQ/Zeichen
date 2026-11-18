from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, union, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..errors import conflict, invalid_request, not_found
from ..models import Activity, Project, Requirement, Task, User
from ..models.requirement_board import RequirementAssigneeHistory as History, RequirementBlocker as Edge
from ..v2.resource_refs import ResourceKind, ResourceRef
from ..v2.timeline import record_system_event
from ..v2.timeline_models import TimelineEntry, TimelineRevision
from .permissions import require_project_role
from .user_profiles import avatar_url, display_name
from .short_codes import require_valid_code


def remember_assignees(db, task, *ids):
    values = sorted({value for value in ids if value})
    if values:
        insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
        db.execute(insert(History).values([
            dict(project_id=task.project_id, requirement_code=task.requirement_id, user_id=value)
            for value in values
        ]).on_conflict_do_nothing())


def participation(project_id, codes=None):
    def source(scope, requirement, person):
        query = select(requirement.label("code"), person.label("actor")).where(
            scope == project_id, person.is_not(None))
        return query.where(requirement.in_(codes)) if codes is not None else query

    assignment_actions = source(Task.project_id, Task.requirement_id, Activity.actor_id).join(
        Activity, and_(Activity.project_id == Task.project_id, Activity.target_id == Task.code,
                       Activity.target_type == "task", Activity.action.in_(["assign", "claim", "unassign"])))
    return union(
        source(Requirement.project_id, Requirement.code, Requirement.created_by),
        source(Task.project_id, Task.requirement_id, Task.created_by),
        source(Task.project_id, Task.requirement_id, Task.assignee_id),
        source(History.project_id, History.requirement_code, History.user_id),
        source(TimelineEntry.project_id, TimelineEntry.requirement_code, TimelineEntry.actor_id)
        .where(TimelineEntry.kind == "manual"),
        assignment_actions,
    ).subquery()


def my_requirements(project_id, user):
    participants = participation(project_id)
    person = user.owner_id or user.id
    return select(participants.c.code).join(User, User.id == participants.c.actor).where(
        or_(User.id == person, User.owner_id == person))


def recent_activity(project_id):
    """Combine document updates, child work and discussion before board pagination."""
    activity = union_all(
        select(Requirement.code.label("code"), Requirement.updated_at.label("at"))
        .where(Requirement.project_id == project_id),
        select(Task.requirement_id, Task.updated_at).where(Task.project_id == project_id),
        select(TimelineRevision.requirement_code, TimelineRevision.created_at)
        .where(TimelineRevision.project_id == project_id),
        select(TimelineEntry.requirement_code, TimelineEntry.occurred_at)
        .where(TimelineEntry.project_id == project_id, TimelineEntry.kind == "system",
               or_(TimelineEntry.source_task_code.is_not(None),
                   TimelineEntry.event_type.in_(["requirement.blockers_changed", "legacy.activity"]))),
    ).subquery()
    return select(activity.c.code, func.max(activity.c.at).label("last_activity_at")).group_by(activity.c.code).subquery()


def board_details(db, project_id, codes):
    result = {code: {"participants": [], "blocked_by": [], "blocks": [], "blocked": False,
                     "task_count": 0, "done_task_count": 0} for code in codes}
    if not result:
        return result
    counts = select(Task.requirement_id, Task.status, func.count()).where(
        Task.project_id == project_id, Task.requirement_id.in_(codes),
        Task.deleted_at.is_(None)).group_by(Task.requirement_id, Task.status)
    for code, status, count in db.execute(counts):
        result[code]["task_count"] += count
        if status == "done":
            result[code]["done_task_count"] = count
    actors = participation(project_id, codes)
    for code, user in db.execute(select(actors.c.code, User).join(User, User.id == actors.c.actor)
                                 .order_by(func.coalesce(User.nickname, User.username), User.id)):
        result[code]["participants"].append({"id": str(user.id), "name": display_name(user), "avatar": avatar_url(user)})
    for field, source, dest in (("blocked_by", Edge.requirement_code, Edge.blocker_code),
                                 ("blocks", Edge.blocker_code, Edge.requirement_code)):
        neighbors = select(source, Requirement).join_from(Edge, Requirement, and_(
            Requirement.project_id == Edge.project_id, Requirement.code == dest)).where(
            Edge.project_id == project_id, source.in_(codes), Requirement.deleted_at.is_(None))
        for code, item in db.execute(neighbors.order_by(Requirement.code)):
            result[code][field].append({"id": item.code, "title": item.title, "status": item.status})
            if field == "blocked_by" and item.status != "done":
                result[code]["blocked"] = True
    return result


def set_blockers(db: Session, actor: User, code: str, project_id: UUID | None,
                 blockers: list[str], expected: list[str] | None = None):
    from .requirements import get_requirement

    item = get_requirement(db, actor, code, project_id)
    pid = item.project_id
    require_project_role(db, actor.id, pid, min_level="editor")
    for blocker in blockers:
        require_valid_code("requirement", blocker)
    wanted = set(blockers)
    if code in wanted or len(wanted) != len(blockers):
        raise invalid_request("前置需求不能重复或指向自身")
    # Serialize graph edits per project before testing reachability.
    if db.get_bind().dialect.name == "sqlite":
        db.execute(delete(Edge).where(False))
    else:
        db.execute(select(Project.id).where(Project.id == pid).with_for_update())
    if wanted:
        valid = db.scalars(select(Requirement.code).where(Requirement.project_id == pid,
            Requirement.code.in_(wanted), Requirement.deleted_at.is_(None))).all()
        if set(valid) != wanted:
            raise not_found("前置需求不存在")
    graph = defaultdict(set)
    for src, dest in db.execute(select(Edge.requirement_code, Edge.blocker_code).where(Edge.project_id == pid)):
        graph[src].add(dest)
    previous = graph[code]
    active_previous = set(db.scalars(select(Requirement.code).where(
        Requirement.project_id == pid, Requirement.code.in_(previous), Requirement.deleted_at.is_(None))))
    if expected is not None and active_previous != set(expected):
        raise conflict("前置需求已被修改，请刷新后重试")
    # A trashed dependency is hidden until restored, including during unrelated edits.
    wanted |= previous - active_previous
    pending = list(wanted)
    visited = set()
    while pending:
        node = pending.pop()
        if node == code:
            raise conflict("前置需求形成循环")
        if node not in visited:
            visited.add(node)
            pending.extend(graph[node] - visited)
    if previous != wanted:
        db.execute(delete(Edge).where(Edge.project_id == pid, Edge.requirement_code == code,
                                      Edge.blocker_code.in_(previous - wanted)))
        db.add_all([Edge(project_id=pid, requirement_code=code, blocker_code=b) for b in wanted-previous])
        record_system_event(db, actor.id, ResourceRef(pid, ResourceKind.REQUIREMENT, code),
                            event_type="requirement.blockers_changed",
                            event_data={"before": sorted(previous), "after": sorted(wanted)})
    db.commit()
    return item
