"""A Markdown edit made through either channel updates the same backlink index."""
from uuid import uuid4

from app.tests.test_mcp_e2e import channels, mcp_server


def test_web_and_mcp_share_current_markdown_links(channels, mcp_server):
    web, agent = channels
    pid = agent.call("project.create", name="跨端交付")["id"]
    base = f"/api/projects/{pid}"
    scope = {"project_id": pid}
    target = agent.call("wiki.create", **scope, request_id=str(uuid4()), content={"title": "目标"})["id"]
    markdown = f"[规格](/projects/{pid}/wiki/{target})"
    response = web.post(f"{base}/requirements", json={"title": "来源", "description": markdown})
    assert response.status_code == 201, response.text
    req = response.json()["id"]
    assert agent.call("requirements.get", **scope, id=req)["description"] == markdown
    bound = {"target_kind": "wiki", "target_id": target}
    assert [r["id"] for r in agent.call("markdown.backlinks", **scope, **bound)["items"]] == [req]
    updated = agent.call("requirements.update", **scope, id=req, expected_version=1, description="已去掉正文链接")
    assert updated["version"] == 2
    assert web.get(f"{base}/markdown/backlinks", params=bound).json()["items"] == []
    assert web.get(f"{base}/requirements/{req}").json()["description"] == "已去掉正文链接"
    src = agent.call("wiki.create", **scope, request_id=str(uuid4()), content={"title": "出处", "body": markdown})
    assert [r["id"] for r in web.get(f"{base}/markdown/backlinks", params=bound).json()["items"]] == [src["id"]]
    assert web.patch(f"/api/requirements/{req}?project_id={pid}", json={"expected_version": 2, "description": markdown}).is_success
    first = agent.call("markdown.backlinks", **scope, **bound, limit=1)
    second = web.get(f"{base}/markdown/backlinks", params={**bound, "limit": 1, "cursor": first["next_cursor"]}).json()
    assert {first["items"][0]["id"], second["items"][0]["id"]} == {req, src["id"]}
    assert not second["next_cursor"]
    # Follow this same requirement from its project and spec through acceptance and delivery.
    assert web.get(base).json()["name"] == "跨端交付"
    assert web.post(f"{base}/requirements/{req}/status", json={"status": "verifying"}).is_success
    receipt = agent.call("requirements.reject", **scope, id=req, reason="补交验收文件", request_id=str(uuid4()))
    trail = web.get(f"{base}/requirements/{req}/timeline", params={"keyword": "补交验收文件"}).json()
    assert [row["id"] for row in trail["items"]] == [receipt["entry_id"]]
    task = web.post(f"{base}/tasks", json={"requirement_id": req, "title": "补交验收文件",
                                         "assignee_id": mcp_server["agent_id"]}).json()["id"]
    assert agent.call("tasks.get", **scope, id=task)["assignee_id"] == mcp_server["agent_id"]
    library = f"/api/v2/projects/{pid}/files"
    file_id = web.post(library, params={"name": "acceptance.txt", "request_id": str(uuid4())},
                       content=b"verified").json()["id"]
    target_task = {"target_kind": "tasks", "target_id": task}
    assert agent.call("files.link", **scope, file_id=file_id, **target_task)["changed"]
    assert web.get(f"{library}/associations", params=target_task).json()["items"][0]["id"] == file_id
    assert agent.call("files.related", **scope, **target_task)["items"][0]["id"] == file_id
    assert not any(t.startswith("ref.") for t in agent.list_tools())
    assert web.post(f"/api/targets/requirement/{req}/references", json={}).status_code == 404


def test_replay_legacy_references_and_preserve_edits(world, db):
    from datetime import UTC, datetime, timedelta
    from app.models import Reference, Requirement, Task
    from app.v2 import work_content
    from app.v2.import_legacy_references import migrate_references
    from app.v2.wiki import WikiContent, create_wiki
    from app.v2.wiki_models import Wiki, WikiReference

    actor = world["admin"]
    pid = world["project"].id
    wiki_id = create_wiki(db, actor.id, pid, request_id=uuid4(), content=WikiContent(title="旧 Wiki", body="原文"))["id"]
    task_parent = work_content.create(db, actor, pid, "requirements", "需求", None, None)
    req = task_parent["id"]
    task_id = work_content.create(db, actor, pid, "tasks", "子任务", None, None, requirement_id=req)["id"]
    task = db.get(Task, (pid, task_id))
    task.legacy_code = "TASK-9"
    removed = work_content.create(db, actor, pid, "requirements", "已解除关联",
                                  f"[旧链接](/projects/{pid}/wiki/{wiki_id})", None)
    body = db.get(Requirement, (pid, removed["id"]))
    work_content.revise(db, actor, body, None, "编辑后已删除链接", 1)

    def edge(source, src_id, target, dst_id):
        value = Reference(project_id=pid, from_type=source, from_id=src_id, to_type=target,
                          to_id=dst_id, type="mentions", created_at=datetime.now(UTC)-timedelta(days=1))
        db.add(value)
        return value

    edge("document", wiki_id, "task", "TASK-9")
    edge("requirement", removed["id"], "document", wiki_id)
    edge("project", str(pid), "requirement", req)
    pending = edge("document", wiki_id, "document", "DOC-998")
    counts, exceptions = migrate_references(db)
    assert counts == {"archived": 3, "updated_bodies": 2}
    assert exceptions == [{"reference_id": str(pending.id), "reason": "unresolved_source_or_target"}]
    wiki = db.get(Wiki, (pid, wiki_id))
    assert wiki.body.startswith("原文") and f"/projects/{pid}/tasks/{task_id}" in wiki.body and wiki.version_no == 2
    assert db.get(WikiReference, (pid, wiki_id, 2, "tasks", task_id))
    assert body.description == "编辑后已删除链接" and body.version == 2
    assert migrate_references(db) == ({"archived": 0, "updated_bodies": 0}, exceptions)
