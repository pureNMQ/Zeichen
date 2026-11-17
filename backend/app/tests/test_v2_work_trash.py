from app.models import Requirement, Task
from app.tests.conftest import login


def test_restore_requirement_hides_active_children_and_preserves_independently_deleted_task(client, db, world):
    pid = world["project"].id
    db.add(Requirement(project_id=pid, code="REQ-1", title="Bundle", status="backlog"))
    db.flush()
    db.add_all([
        Task(project_id=pid, code="TASK-1", title="Active", requirement_id="REQ-1"),
        Task(project_id=pid, code="TASK-2", title="Deleted independently", requirement_id="REQ-1"),
    ])
    db.commit()
    login(client, "admin", "admin-pass-1")
    params = {"project_id": str(pid)}
    assert client.post("/api/tasks/TASK-2/delete", params=params).status_code == 200
    assert client.post("/api/requirements/REQ-1/delete", params=params, json={"confirm_task_count": 1}).status_code == 200
    assert client.get("/api/tasks/TASK-1", params=params).status_code == 404
    assert client.get("/api/search", params={"q": "Active", "domain": "task", **params}).json()["items"] == []
    trash = f"/api/v2/projects/{pid}/trash/work"
    assert client.get(f"{trash}/requirement/REQ-1").json()["affected_tasks"] == 1
    assert [item["id"] for item in client.get(trash, params={"kind": "task"}).json()["items"]] == ["TASK-2"]
    assert client.post(f"{trash}/task/TASK-2/restore").status_code == 409
    assert client.post(f"{trash}/requirement/REQ-1/restore").status_code == 200
    assert client.get("/api/tasks/TASK-1", params=params).status_code == 200
    assert client.get("/api/tasks/TASK-2", params=params).status_code == 404
