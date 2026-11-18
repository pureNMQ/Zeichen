"""Task-to-task blockers are no longer a supported input or response."""
from app.tests.conftest import login


def test_task_blocker_fields_removed(client, world):
    login(client, "admin", "admin-pass-1")
    project = str(world["project"].id)
    req = client.post(f"/api/projects/{project}/requirements", json={"title": "范围"}).json()
    draft = {"title": "执行", "requirement_id": req["id"]}
    url = f"/api/projects/{project}/tasks"
    assert client.post(url, json={**draft, "blocked_by": []}).status_code == 422
    task = client.post(url, json=draft).json()
    assert "blocked_by" not in task and "blocked" not in task
    assert client.patch(f"/api/tasks/{task['id']}", json={"blocked_by": []}).status_code == 422
