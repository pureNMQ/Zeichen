from contextlib import nullcontext
from uuid import UUID, uuid4

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from sqlalchemy import func, select

from app.errors import AppError
from app.mcp_server import tools
from app.models import ProjectMember, Requirement
from app.v2 import notifications, timeline, wiki
from app.v2.notification_models import Notification
from app.v2.resource_refs import ResourceKind, ResourceRef

from .conftest import login, make_user


@pytest.fixture
def scope(db, world):
    project_id = world["project"].id
    db.add(Requirement(project_id=project_id, code="REQ-1", title="通知", status="backlog"))
    db.commit()
    return ResourceRef(project_id, ResourceKind.REQUIREMENT, "REQ-1")


def mention(scope, person):
    ref = ResourceRef(scope.project_id, ResourceKind.PERSON, str(person.id))
    return f"[@{person.username}]({ref.path})"


def inbox(db, actor):
    return notifications.list_notifications(db, actor)["items"]


def test_reply_and_mentions_deduplicate_and_first_reader_is_shared(db, world, scope):
    owner, agent, author = world["agent_owner"], world["agent"], world["admin"]
    initial = timeline.append_entry(db, owner, scope, request_id=uuid4(), body="请评审")
    db.commit()
    args = {
        "request_id": uuid4(),
        "body": f"已完成，{mention(scope, owner)} {mention(scope, agent)}",
        "reply_to": UUID(initial["entry_id"]),
    }
    reply = timeline.append_entry(db, author, scope, **args)
    db.commit()
    assert timeline.append_entry(db, author, scope, **args) == reply
    [shared] = inbox(db, owner)
    assert inbox(db, agent) == [shared]
    assert inbox(db, author) == []
    assert shared["read_at"] is None and shared["reply_user_id"] == str(owner.id)
    assert shared["source_path"] == f'{scope.path}#timeline-{reply["entry_id"]}'
    assert set(shared["mentioned_user_ids"]) == {str(owner.id), str(agent.id)}
    assert notifications.unread_count(db, owner) == 1
    notification_id = UUID(shared["id"])
    read = notifications.mark_read(db, agent, notification_id)
    db.commit()
    assert notifications.mark_read(db, owner, notification_id) == read
    assert read["read_by_id"] == str(agent.id) and read["read_at"] is not None
    assert notifications.unread_count(db, owner) == notifications.unread_count(db, agent) == 0


def test_only_effective_person_links_notify_and_agent_cannot_read_owner_only(db, world, scope):
    owner, agent, reader = world["agent_owner"], world["agent"], world["member"]
    outsider = make_user(db, "outside")
    ignored = mention(scope, reader)
    foreign = ResourceRef(uuid4(), ResourceKind.PERSON, str(reader.id)).path
    body = (
        f"{mention(scope, owner)} {mention(scope, outsider)} {mention(scope, agent)}\n\n"
        f"`{ignored}` and !{ignored} with [foreign]({foreign}).\n\n"
        f"    {ignored}\n\n```md\n{ignored}\n```\n\n@{reader.username}"
    )
    timeline.append_entry(db, agent, scope, request_id=uuid4(), body=body)
    db.commit()
    [owner_only] = inbox(db, owner)
    assert owner_only["visibility"] == "owner_only"
    assert owner_only["mentioned_user_ids"] == [str(owner.id)]
    assert inbox(db, reader) == inbox(db, outsider) == inbox(db, agent) == []
    for operation in (notifications.get_notification, notifications.mark_read):
        with pytest.raises(AppError) as error:
            operation(db, agent, UUID(owner_only["id"]))
        assert error.value.code == "not_found"
    assert notifications.unread_count(db, owner) == 1


def test_source_permission_is_rechecked_after_project_role_or_requirement_changes(db, world, scope):
    agent, owner, author = world["agent"], world["agent_owner"], world["admin"]
    timeline.append_entry(db, author, scope, request_id=uuid4(), body=mention(scope, agent))
    db.commit()
    note_id = UUID(inbox(db, agent)[0]["id"])
    membership = db.scalar(select(ProjectMember).where(
        ProjectMember.project_id == scope.project_id, ProjectMember.user_id == owner.id
    ))
    db.delete(membership)
    db.commit()
    assert notifications.unread_count(db, owner) == 0
    with pytest.raises(AppError) as error:
        notifications.get_notification(db, owner, note_id)
    assert error.value.code == "not_found"
    db.add(ProjectMember(project_id=scope.project_id, user_id=owner.id, role="editor"))
    db.commit()
    assert notifications.unread_count(db, agent) == 1
    requirement = db.get(Requirement, (scope.project_id, scope.identifier))
    requirement.deleted_at = world["project"].created_at
    db.commit()
    assert inbox(db, agent) == []
    with pytest.raises(AppError) as error:
        notifications.mark_read(db, owner, note_id)
    assert error.value.code == "not_found"


def test_wiki_and_timeline_edits_only_notify_new_mentions(db, world, scope):
    author, owner, agent, reader = world["admin"], world["agent_owner"], world["agent"], world["member"]
    linked = mention(scope, agent)
    command = {
        "request_id": uuid4(), "content": wiki.WikiContent(title="Wiki", body=linked),
    }
    page = wiki.create_wiki(db, author.id, scope.project_id, **command)
    db.commit()
    assert wiki.create_wiki(db, author.id, scope.project_id, **command) == page
    [first] = inbox(db, owner)
    assert first["source_kind"] == "wiki" and first["source_version"] == 1
    code = page["id"]
    wiki.update_wiki(db, author.id, scope.project_id, code, expected_version=1,
                     patch=wiki.WikiPatch(title="Renamed"))
    wiki.update_wiki(db, author.id, scope.project_id, code, expected_version=2,
                     patch=wiki.WikiPatch(body=f"{linked} {mention(scope, reader)}"))
    db.commit()
    assert inbox(db, owner) == [first]
    [wiki_added] = inbox(db, reader)
    assert wiki_added["source_version"] == 3
    draft = timeline.append_entry(db, author, scope, request_id=uuid4(), body="first without mention")
    db.commit()
    entry_id = UUID(draft["entry_id"])
    change = {
        "request_id": uuid4(), "expected_version": 1, "body": linked,
    }
    timeline.revise_entry(db, author, scope, entry_id, **change)
    db.commit()
    assert timeline.revise_entry(db, author, scope, entry_id, **change)["version"] == 2
    timeline.revise_entry(db, author, scope, entry_id, request_id=uuid4(),
                          expected_version=2, body=f"{linked} more text")
    db.commit()
    assert [(note["source_kind"], note["source_version"]) for note in inbox(db, owner)] == [
        ("timeline", 2), ("wiki", 1),
    ]


def test_notification_for_child_of_deleted_wiki_is_hidden_until_restore(db, world, scope):
    author, reader = world["admin"], world["member"]
    project_id = scope.project_id
    parent = wiki.create_wiki(db, author.id, project_id, request_id=uuid4(), content=wiki.WikiContent(title="Parent"))
    wiki.create_wiki(db, author.id, project_id, request_id=uuid4(), parent_id=parent["id"],
                     content=wiki.WikiContent(title="Child", body=mention(scope, reader)))
    db.commit()
    [notice] = inbox(db, reader)
    wiki.delete_wiki(db, author.id, project_id, parent["id"], confirmed_count=2)
    db.commit()

    assert inbox(db, reader) == []
    with pytest.raises(AppError, match="不可见"):
        notifications.mark_read(db, reader, UUID(notice["id"]))
    db.rollback()
    wiki.restore_wiki(db, author.id, project_id, parent["id"])
    db.commit()
    assert inbox(db, reader) == [notice]


def test_rollback_clears_notifications_and_web_open_acknowledges(client, db, world, scope):
    author = world["agent"]
    recipient = world["admin"]
    params = {"request_id": uuid4(), "body": mention(scope, recipient)}
    timeline.append_entry(db, author, scope, **params)
    assert db.scalar(select(func.count()).select_from(Notification)) == 1
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Notification)) == 0
    timeline.append_entry(db, author, scope, **params)
    db.commit()
    login(client, "admin", "admin-pass-1")
    base = "/api/v2/notifications"
    [notice] = client.get(base).json()["items"]
    assert notice["read_at"] is None
    assert client.get(f'{base}/{notice["id"]}').json()["read_at"] is None
    assert client.get(f"{base}/unread-count").json() == {"count": 1}
    opened = client.post(f'{base}/{notice["id"]}/open').json()
    assert opened["read_by_id"] == str(recipient.id)
    assert client.get(f"{base}/unread-count").json() == {"count": 0}


def test_mcp_requires_explicit_shared_acknowledgement(db, world, scope, monkeypatch):
    author, agent, owner = world["admin"], world["agent"], world["agent_owner"]
    timeline.append_entry(db, author, scope, request_id=uuid4(), body=mention(scope, agent))
    timeline.append_entry(db, agent, scope, request_id=uuid4(), body=mention(scope, owner))
    db.commit()
    owner_only = next(note for note in inbox(db, owner) if note["visibility"] == "owner_only")
    monkeypatch.setattr(tools, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(tools.auth, "current_principal", lambda session: agent)
    handlers = {}

    class Tools:
        def tool(self, *, name):
            def register(function):
                handlers[name] = function
                return function
            return register

    tools._register_all(Tools())
    [shared] = handlers["notifications.list"](unread_only=True)["items"]
    assert handlers["notifications.get"](shared["id"])["read_at"] is None
    with pytest.raises(ToolError, match="not_found"):
        handlers["notifications.mark_read"](owner_only["id"])
    acknowledged = handlers["notifications.mark_read"](shared["id"])
    assert acknowledged["read_by_id"] == str(agent.id)
    assert not handlers["notifications.list"](unread_only=True)["items"]
    assert notifications.unread_count(db, owner) == 1
