"""Stable task links across the requirement-local numbering migration."""

import runpy
from pathlib import Path
from uuid import uuid4

from app.models import Requirement, Task
from app.tests.conftest import login


def test_old_task_link_resolves_only_to_migrated_task(client, db, world):
    project = world["project"].id
    db.add(Requirement(project_id=project, code="REQ-8", title="现有需求"))
    db.flush()
    db.add(Task(project_id=project, requirement_id="REQ-8", code="REQ-8-T1",
                legacy_code="TASK-14", title="现有任务"))
    db.commit()
    login(client, "admin", "admin-pass-1")
    params = {"project_id": str(project)}
    assert client.get("/api/tasks/TASK-14", params=params).json()["id"] == "REQ-8-T1"
    assert client.get("/api/tasks/TASK-1", params=params).status_code == 404
    assert client.get("/api/tasks/REQ-8-T1", params=params).json()["requirement_id"] == "REQ-8"


def test_link_migration_preserves_history_when_destination_is_uncertain():
    revision = Path(__file__).parents[2] / "alembic/versions/v2taskidentity_scoped_tasks.py"
    rewrite = runpy.run_path(str(revision))["_rewrite"]
    project = str(uuid4())
    path = f"/projects/{project}/tasks/TASK-8"
    old_link = f"[工作]({path})"
    new_link = old_link.replace("/TASK-8", "/REQ-2-T3")
    old_deep = f"[工作](/projects/{project}/requirements/REQ-1?task=TASK-8)"
    new_deep = f"[工作](/projects/{project}/requirements/REQ-2?task=REQ-2-T3)"
    examples = f"`{old_link}`\n~~~\n{old_link}\n~~~\n[未知]({path}8)\n文本 TASK-8\n"
    assert rewrite(old_link + "\n" + old_deep + "\n" + examples,
                   {(project, "TASK-8"): "REQ-2-T3"}) == new_link + "\n" + new_deep + "\n" + examples
