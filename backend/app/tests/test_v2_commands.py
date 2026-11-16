from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.errors import AppError, invalid_request
from app.v2.commands import CommandReceipt, execute_once


def test_retry_replays_original_receipt_and_rejects_different_body(db, world):
    project = world["project"]
    key = dict(project_id=project.id, actor_id=world["agent"].id,
               operation="project.rename", request_id=uuid4())
    db.commit()
    calls = []

    def apply():
        calls.append(True)
        project.name = "new name"
        return {"id": str(project.id), "changed": True}

    with db.begin():
        saved = execute_once(db, **key, payload={"name": "new name"}, apply=apply)
    with db.begin():
        assert execute_once(db, **key, payload={"name": "new name"}, apply=apply) == saved
    with pytest.raises(AppError) as caught, db.begin():
        execute_once(db, **key, payload={"name": "different"}, apply=apply)

    assert caught.value.code == "conflict"
    assert calls == [True]
    assert project.name == "new name"


def test_failed_command_rolls_back_change_and_does_not_consume_request_id(db, world):
    project = world["project"]
    key = dict(project_id=project.id, actor_id=world["agent"].id,
               operation="project.rename", request_id=uuid4())
    db.commit()

    def fail():
        project.name = "failed"
        db.flush()
        raise invalid_request("simulated validation failure")

    with pytest.raises(AppError), db.begin():
        execute_once(db, **key, payload={"name": "failed"}, apply=fail)

    with db.begin():
        assert project.name == "demo"
        assert db.scalar(select(func.count()).select_from(CommandReceipt)) == 0
        assert execute_once(db, **key, payload={"name": "failed"}, apply=lambda: {"changed": False}) == {
            "changed": False
        }
