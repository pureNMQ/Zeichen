from uuid import uuid4

import pytest

from app.errors import AppError
from app.models import Project
from app.v2.markdown_refs import extract_markdown_refs
from app.v2.resource_refs import ResourceKind, ResourceRef
from app.v2.wiki import (
    WikiContent,
    WikiPatch,
    WikiReferenceUse,
    create_wiki,
    find_reference_uses,
    read_references,
    read_version,
    read_wiki,
    restore_wiki_version,
    update_wiki,
)


def test_wiki_authoring_and_restore_snapshot_with_conflict_protection(db, world):
    project_id = world["project"].id
    author = world["agent"].id
    reader = world["member"].id
    original = WikiContent(title="原文", summary="摘要", category="自定义分类", tags=["测试"], body="内容")
    request_id = uuid4()
    db.commit()
    with db.begin():
        created = create_wiki(db, author, project_id, request_id=request_id, content=original)
    with db.begin():
        replayed = create_wiki(db, author, project_id, request_id=request_id, content=original)
    assert created == replayed
    assert "body" not in created and "summary" not in created
    code = created["id"]

    with db.begin():
        revised = update_wiki(db, author, project_id, code, expected_version=1,
                              patch=WikiPatch(title="新版", summary=None, tags=[]))
    assert revised["version"] == 2
    with pytest.raises(AppError) as stale, db.begin():
        update_wiki(db, author, project_id, code, expected_version=1, patch=WikiPatch(body="过期修改"))
    assert stale.value.code == "conflict"
    assert "2" in stale.value.message

    with db.begin():
        current = read_wiki(db, reader, project_id, code)
        assert (current.title, current.body, current.summary, current.category, current.tags) == (
            "新版", "内容", None, "自定义分类", [],
        )
        assert read_version(db, reader, project_id, code, 1).created_by == author
        restored = restore_wiki_version(db, author, project_id, code, expected_version=2, from_version=1)
    assert restored["version"] == 3
    with db.begin():
        assert WikiContent.model_validate(read_wiki(db, reader, project_id, code)) == original
        assert read_version(db, reader, project_id, code, 2).title == "新版"


def test_current_and_historical_references_are_independent_and_atomic(db, world):
    project_id = world["project"].id
    actor = world["admin"].id
    ref = ResourceRef(project_id, ResourceKind.FILE, str(uuid4()))
    db.commit()
    with db.begin():
        doc = create_wiki(db, actor, project_id, request_id=uuid4(),
                          content=WikiContent(title="文件", body=f"![图]({ref.path})"))
    code = doc["id"]

    with pytest.raises(RuntimeError), db.begin():
        update_wiki(db, actor, project_id, code, expected_version=1, patch=WikiPatch(body="无文件"))
        raise RuntimeError("simulate failure in a later command step")

    with db.begin():
        assert read_references(db, actor, project_id, code) == [ref]
        update_wiki(db, actor, project_id, code, expected_version=1, patch=WikiPatch(body="无文件"))
    with db.begin():
        assert read_references(db, actor, project_id, code) == []
        assert read_references(db, actor, project_id, code, version_no=1) == [ref]
        assert find_reference_uses(db, actor, ref) == ([], None)
        assert find_reference_uses(db, actor, ref, include_history=True) == ([WikiReferenceUse(code, 1, False)], None)
        restore_wiki_version(db, actor, project_id, code, expected_version=2, from_version=1)
    with db.begin():
        current, cursor = find_reference_uses(db, actor, ref, include_history=True, limit=1)
        assert current == [WikiReferenceUse(code, 1, False)]
        assert cursor is not None
        assert find_reference_uses(db, actor, ref, include_history=True, after=cursor, limit=1) == (
            [WikiReferenceUse(code, 3, True)], None,
        )


def test_wiki_versions_and_parent_lookup_stay_inside_the_project(db, world):
    project_id = world["project"].id
    author = world["admin"].id
    outsider = world["member"].id
    db.commit()
    with db.begin():
        remote = Project(team_id=world["team"].id, name="Private")
        db.add(remote)
        db.flush()
        remote_id = remote.id
        remote_doc = create_wiki(db, author, remote_id, request_id=uuid4(), content=WikiContent(title="私有"))

    with pytest.raises(AppError) as rejected, db.begin():
        read_version(db, outsider, remote_id, remote_doc["id"], 1)
    assert rejected.value.code == "not_found"
    with pytest.raises(AppError) as bad_parent, db.begin():
        create_wiki(db, author, project_id, request_id=uuid4(), content=WikiContent(title="父级跨项目"),
                    parent_id=remote_doc["id"])
    assert bad_parent.value.code == "not_found"

    with db.begin():
        local_doc = create_wiki(db, author, project_id, request_id=uuid4(), content=WikiContent(title="公开"))
        assert local_doc["id"] == remote_doc["id"]
        assert read_version(db, outsider, project_id, local_doc["id"], 1).title == "公开"


def test_markdown_reference_index_only_uses_rendered_standard_links_and_images():
    project_id = uuid4()
    wiki = ResourceRef(project_id, ResourceKind.WIKI, "TERM-1")
    task = ResourceRef(project_id, ResourceKind.TASK, "TASK-3")
    req = ResourceRef(project_id, ResourceKind.REQUIREMENT, "REQ-2")
    file = ResourceRef(project_id, ResourceKind.FILE, str(uuid4()))
    remote = ResourceRef(uuid4(), ResourceKind.WIKI, "DOC-1")
    body = f"""[带标题]({wiki.path}#section) [重复]({wiki.path})

![配图][file] [任务]({task.path})

[file]: <{file.path}> "A file"

`[inline code]({req.path})`

```md
[fenced example]({req.path})
```

    [indented example]({req.path})

<!-- [comment example]({req.path}) -->

[外部项目]({remote.path}) [非法](/projects/{project_id}/wiki/DOC-00) [[REQ-2]]
"""
    assert extract_markdown_refs(body, project_id) == {wiki, task, file}
