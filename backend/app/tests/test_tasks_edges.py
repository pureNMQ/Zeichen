"""任务服务补边测试(规格书 §3.2:所有权、指派、认领、分页、软删)。"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import requirements as req_svc
from app.services import tasks as svc


def make_task(db: Session, world: dict, title="任务", **kw) -> dict:
    task = svc.create_task(db, world["admin"], world["project"].id, title, **kw)
    return {"id": task.id, "node": task}


class TestCreateAndGetEdges:
    def test_empty_title(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.create_task(db, world["admin"], world["project"].id, "   ")
        assert e.value.code == "invalid_request"

    def test_get_missing_task(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.get_task(db, world["member"], uuid.uuid4())
        assert e.value.code == "not_found"

    def test_assignee_must_exist_and_be_member(self, db: Session, world: dict):
        from app.tests.conftest import make_user

        with pytest.raises(AppError) as e:
            svc.create_task(db, world["admin"], world["project"].id, "t", assignee_id=uuid.uuid4())
        assert e.value.code == "not_found"
        outsider = make_user(db, "outsider", role="member")
        with pytest.raises(AppError) as e:
            svc.create_task(db, world["admin"], world["project"].id, "t", assignee_id=outsider.id)
        assert e.value.code == "invalid_request"
        assert "项目成员" in e.value.message


class TestUpdateEdges:
    def test_update_validation_and_description(self, db: Session, world: dict):
        task = make_task(db, world)["id"]
        with pytest.raises(AppError) as e:
            svc.update_task(db, world["admin"], task, title="  ")
        assert e.value.code == "invalid_request"
        updated = svc.update_task(db, world["admin"], task, description="描述更新")
        assert updated.description == "描述更新"


class TestListFilters:
    def test_filter_by_status_and_assignee_and_pagination(self, db: Session, world: dict):
        req = req_svc.create_requirement(db, world["admin"], world["project"].id, "需求")
        req_svc.set_requirement_status(db, world["admin"], req.id, "backlog")
        make_task(db, world, "任务一", requirement_id=req.id, assignee_id=world["agent"].id)
        svc.set_task_status(db, world["agent"], make_task(db, world, "任务二")["id"], "in_progress")
        make_task(db, world, "任务三")

        page = svc.list_tasks(db, world["member"], world["project"].id, None, None, None, None, 20)
        assert len(page["items"]) == 3
        by_status = svc.list_tasks(db, world["member"], world["project"].id, None, None, "in_progress", None, 20)
        assert [i["title"] for i in by_status["items"]] == ["任务二"]
        by_agent = svc.list_tasks(db, world["member"], world["project"].id, None, world["agent"].id, None, None, 20)
        assert [i["title"] for i in by_agent["items"]] == ["任务一"]
        by_req = svc.list_tasks(db, world["member"], world["project"].id, req.id, None, None, None, 20)
        assert [i["title"] for i in by_req["items"]] == ["任务一"]
        page1 = svc.list_tasks(db, world["member"], world["project"].id, None, None, None, None, 2)
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None
        page2 = svc.list_tasks(db, world["member"], world["project"].id, None, None, None, page1["next_cursor"], 2)
        assert len(page2["items"]) == 1
        assert page2["next_cursor"] is None


class TestAssignAndClaimEdges:
    def test_assign_to_terminal_task_conflicts(self, db: Session, world: dict):
        task = make_task(db, world)["id"]
        svc.set_task_status(db, world["admin"], task, "done")
        with pytest.raises(AppError) as e:
            svc.assign_task(db, world["admin"], task, world["agent"].id)
        assert e.value.code == "conflict"

    def test_claim_terminal_task_conflicts(self, db: Session, world: dict):
        task = make_task(db, world, assignee_id=world["agent"].id)["id"]
        svc.set_task_status(db, world["agent"], task, "done")
        with pytest.raises(AppError) as e:
            svc.claim_task(db, world["admin"], task)
        assert e.value.code == "conflict"

    def test_claim_already_assigned_conflicts(self, db: Session, world: dict):
        task = make_task(db, world, assignee_id=world["agent"].id)["id"]
        with pytest.raises(AppError) as e:
            svc.claim_task(db, world["agent"], task)
        assert e.value.code == "conflict"

    def test_unassign_terminal_task_conflicts(self, db: Session, world: dict):
        task = make_task(db, world, assignee_id=world["agent"].id)["id"]
        svc.set_task_status(db, world["agent"], task, "done")
        with pytest.raises(AppError) as e:
            svc.unassign_task(db, world["agent"], task)
        assert e.value.code == "conflict"

    def test_claim_concurrent_race_is_conflict(self, db: Session, world: dict, monkeypatch):
        task = make_task(db, world)["id"]
        from sqlalchemy.exc import OperationalError

        def boom(*args, **kwargs):
            raise OperationalError("UPDATE", {}, Exception("locked"))

        monkeypatch.setattr(db, "execute", boom)
        with pytest.raises(AppError) as e:
            svc.claim_task(db, world["agent"], task)
        assert e.value.code == "conflict"


class TestRestoreEdges:
    def test_restore_missing_or_alive_task(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.restore_task(db, world["admin"], uuid.uuid4())
        assert e.value.code == "not_found"
        task = make_task(db, world)["id"]
        with pytest.raises(AppError) as e:
            svc.restore_task(db, world["admin"], task)
        assert e.value.code == "not_found"
