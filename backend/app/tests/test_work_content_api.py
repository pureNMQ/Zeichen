from uuid import uuid4

import pytest

from app.config import get_settings
from app.tests.conftest import login
from app.v2.work_content_models import WorkVersion


@pytest.mark.parametrize("kind", ["requirements", "tasks"])
def test_editor_round_trip_and_revisions(client, world, kind):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    root = f"/api/projects/{pid}"
    parent = client.post(f"{root}/requirements", json={"title": "上下文"}).json()["id"]
    client.post(f"/api/requirements/{parent}/status", json={"status": "backlog"})
    text = ("## 目标\n\n" + "工程化排查" * 240 + f"\n\n[需求](/projects/{pid}/requirements/{parent})")
    payload = {"title": "初稿", "description": text, "request_id": str(uuid4())}
    if kind == "tasks":
        payload["requirement_id"] = parent
    created = client.post(f"{root}/{kind}", json=payload)
    assert created.status_code == 201, created.text
    created = created.json()
    assert created["description"] == text and created["version"] == 1
    code = created["id"]
    list_row = next(row for row in client.get(f"{root}/{kind}").json()["items"] if row["id"] == code)
    assert list_row["description_truncated"] and list_row["description"] == text[:240]
    history = f"{root}/{kind}/{code}/versions"
    patch = f"/api/{kind}/{code}?project_id={pid}"
    assert client.patch(patch, json={"description": "无版本"}).status_code == 400
    changed = client.patch(patch, json={"expected_version": 1, "description": ""})
    assert changed.json()["description"] == "" and changed.json()["version"] == 2
    # A dropped HTTP response can be replayed even after another editor changes the item.
    replay = client.post(f"{root}/{kind}", json=payload)
    assert replay.status_code == 201 and replay.json() == created
    assert client.post(f"{root}/{kind}", json={**payload, "title": "不同载荷"}).status_code == 409
    assert len([row for row in client.get(f"{root}/{kind}").json()["items"] if row["title"] == "初稿"]) == 1
    assert client.patch(patch, json={"expected_version": 1, "title": "冲突"}).status_code == 409
    assert client.get(f"{history}/1").json()["description"] == text
    first = client.get(history, params={"limit": 1}).json()
    assert [v["version"] for v in first["items"]] == [2]
    assert "description" not in first["items"][0]
    second = client.get(history, params={"before": first["next_before"]}).json()
    assert [v["version"] for v in second["items"]] == [1]
    restored = client.post(f"{history}/1/restore", json={"expected_version": 2})
    assert restored.status_code == 200, restored.text
    assert restored.json()["description"] == text and restored.json()["version"] == 3
    assert client.post(f"{history}/1/restore", json={"expected_version": 2}).status_code == 409
    assert client.get(f"{history}/2").json()["description"] == ""
    assert client.patch(patch, json={"expected_version": 3, "description": "\x00"}).status_code == 400


def test_work_body_file_references_survive_revisions(client, world, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", str(tmp_path))
    login(client, "admin", "admin-pass-1")
    pid = world["project"].id
    files = f"/api/v2/projects/{pid}/files"
    file = client.post(files, params={"name": "brief.txt", "request_id": str(uuid4())}, content=b"example").json()
    created = client.post(f"/api/projects/{pid}/requirements", json={
        "title": "设计评审", "description": f"[查看资料]({file['href']})",
    }).json()
    candidates = client.get(f"/api/projects/{pid}/completions", params={"mode": "reference", "q": "brief.txt"}).json()["items"]
    assert [(r["kind"], r["href"]) for r in candidates] == [("file", file["href"])]
    usage = f"{files}/{file['id']}/usage"
    rows = client.get(usage).json()["items"]
    assert [(r["label"], r["current"]) for r in rows] == [("设计评审", True)]
    patch = f"/api/requirements/{created['id']}?project_id={pid}"
    assert client.patch(patch, json={"description": "已归档", "expected_version": 1}).status_code == 200
    assert client.get(usage).json()["items"] == []
    old = client.get(usage, params={"include_history": True}).json()["items"]
    assert len(old) == 1 and old[0]["href"].endswith("?version=1") and not old[0]["current"]


def test_revision_with_missing_author_remains_readable(client, world, db):
    login(client, "admin", "admin-pass-1")
    pid = world["project"].id
    root = f"/api/projects/{pid}/requirements"
    code = client.post(root, json={"title": "迁移正文"}).json()["id"]
    first = db.get(WorkVersion, (pid, code, 1))
    first.created_by = None  # A legacy snapshot may predate author tracking.
    db.commit()
    path = f"{root}/{code}/versions"
    [summary] = client.get(path).json()["items"]
    details = client.get(f"{path}/1").json()
    for row in (summary, details):
        assert (row["actor_id"], row["actor_name"], row["actor_is_agent"]) == (None, None, None)


@pytest.mark.parametrize("kind", ["requirements", "tasks"])
def test_related_files_merge_current_body_and_explicit_associations_before_pagination(client, world, tmp_path, monkeypatch, kind):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", str(tmp_path))
    login(client, "admin", "admin-pass-1")
    pid = world["project"].id
    root = f"/api/projects/{pid}"
    files = f"/api/v2/projects/{pid}/files"
    parent = client.post(f"{root}/requirements", json={"title": "上下文"}).json()["id"]
    attached, inline, both = (
        client.post(files, params={"name": name, "request_id": str(uuid4())}, content=b"sample").json()
        for name in ("review.txt", "diagram.png", "brief.txt")
    )
    body = f"[附件]({both['href']}) ![图]({inline['href']}) [再次引用]({both['href']}) [上下文](/projects/{pid}/requirements/{parent})"
    data = {"title": "交付", "description": body}
    if kind == "tasks":
        data["requirement_id"] = parent
    code = client.post(f"{root}/{kind}", json=data).json()["id"]
    association = {"target_kind": kind, "target_id": code}
    for file in (attached, both):
        assert client.put(f"{files}/{file['id']}/usage", params=association).status_code == 200

    listing = f"{files}/associations"
    options = {**association, "include_body": True}
    first = client.get(listing, params={**options, "limit": 2}).json()
    second = client.get(listing, params={**options, "limit": 2, "cursor": first["next_cursor"]}).json()
    assert second["next_cursor"] is None
    assert first["items"] + second["items"] == sorted([
        {**attached, "attached": True, "referenced": False},
        {**inline, "attached": False, "referenced": True},
        {**both, "attached": True, "referenced": True},
    ], key=lambda file: file["id"])
    assert client.get(listing, params={**association, "limit": 2, "cursor": first["next_cursor"]}).status_code == 400
    assert client.get(listing, params=association).json()["items"] == sorted([attached, both], key=lambda file: file["id"])

    assert client.patch(f"/api/{kind}/{code}?project_id={pid}", json={"description": "", "expected_version": 1}).status_code == 200
    remaining = client.get(listing, params=options).json()["items"]
    assert {item["id"] for item in remaining} == {attached["id"], both["id"]}
    assert all(item["attached"] and not item["referenced"] for item in remaining)
    assert client.post(f"{root}/{kind}/{code}/versions/1/restore", json={"expected_version": 2}).status_code == 200
    assert client.delete(f"{files}/{both['id']}/usage", params=association).status_code == 200
    assert client.delete(f"{files}/{both['id']}").status_code == 200
    assert {"id": both["id"], "unavailable": True, "referenced": True, "attached": False} in client.get(listing, params=options).json()["items"]

    if kind == "tasks":
        assert client.post(f"/api/requirements/{parent}/delete", json={"confirm_task_count": 1}).status_code == 200
        assert client.get(listing, params=options).status_code == 404


def test_whole_project_completion_contains_visible_task(client, world):
    login(client, "admin", "admin-pass-1")
    root = f"/api/projects/{world['project'].id}"
    parent = client.post(f"{root}/requirements", json={"title": "上下文"}).json()["id"]
    client.post(f"/api/requirements/{parent}/status", json={"status": "backlog"})
    task = client.post(f"{root}/tasks", json={"title": "并行联调", "requirement_id": parent}).json()["id"]
    result = client.get(root + "/completions", params={"mode": "reference", "q": task}).json()["items"]
    assert len(result) == 1 and result[0]["kind"] == "task" and result[0]["id"] == task
    assert client.post(f"/api/requirements/{parent}/delete", json={"confirm_task_count": 1}).status_code == 200
    assert client.get(root + "/completions", params={"mode": "reference", "q": task}).json()["items"] == []
