"""任务服务补边测试(规格书 §3.2:所有权、指派、认领、分页、软删)。"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import requirements as req_svc
from app.services import tasks as svc


def make_requirement_row(db: Session, world: dict, title="挂载需求"):
    r = req_svc.create_requirement(db, world["admin"], world["project"].id, title)
    req_svc.set_requirement_status(db, world["admin"], r.code, "backlog")
    return r


def make_task(db: Session, world: dict, title="任务", **kw) -> dict:
    if "requirement_id" not in kw:
        kw["requirement_id"] = make_requirement_row(db, world).code
    task = svc.create_task(db, world["admin"], world["project"].id, title, **kw)
    return {"id": task.code, "node": task}


class TestCreateAndGetEdges:
    def test_empty_title(self, db: Session, world: dict):
        rid = make_requirement_row(db, world).code
        with pytest.raises(AppError) as e:
            svc.create_task(db, world["admin"], world["project"].id, "   ", requirement_id=rid)
        assert e.value.code == "invalid_request"

    def test_get_missing_task(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.get_task(db, world["member"], "TASK-999")
        assert e.value.code == "not_found"

    def test_assignee_must_exist_and_be_member(self, db: Session, world: dict):
        from app.tests.conftest import make_user

        rid = make_requirement_row(db, world).code
        with pytest.raises(AppError) as e:
            svc.create_task(
                db, world["admin"], world["project"].id, "t",
                requirement_id=rid, assignee_id=uuid.uuid4(),
            )
        assert e.value.code == "not_found"
        outsider = make_user(db, "outsider", role="member")
        with pytest.raises(AppError) as e:
            svc.create_task(
                db, world["admin"], world["project"].id, "t",
                requirement_id=rid, assignee_id=outsider.id,
            )
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
        req_svc.set_requirement_status(db, world["admin"], req.code, "backlog")
        make_task(db, world, "任务一", requirement_id=req.code, assignee_id=world["agent"].id)
        svc.set_task_status(db, world["agent"], make_task(db, world, "任务二")["id"], "in_progress")
        make_task(db, world, "任务三")

        # 新签名(T1):status 多值(list[str] | None),新增 updated_within_days/keyword
        pid = world["project"].id
        page = svc.list_tasks(
            db=db, user=world["member"], project_id=pid, requirement_id=None,
            assignee_id=None, status=None, cursor=None, limit=20,
            updated_within_days=None, keyword=None,
        )
        assert len(page["items"]) == 3
        by_status = svc.list_tasks(
            db=db, user=world["member"], project_id=pid, requirement_id=None,
            assignee_id=None, status=["in_progress"], cursor=None, limit=20,
            updated_within_days=None, keyword=None,
        )
        assert [i["title"] for i in by_status["items"]] == ["任务二"]
        by_agent = svc.list_tasks(
            db=db, user=world["member"], project_id=pid, requirement_id=None,
            assignee_id=world["agent"].id, status=None, cursor=None, limit=20,
            updated_within_days=None, keyword=None,
        )
        assert [i["title"] for i in by_agent["items"]] == ["任务一"]
        by_req = svc.list_tasks(
            db=db, user=world["member"], project_id=pid, requirement_id=req.code,
            assignee_id=None, status=None, cursor=None, limit=20,
            updated_within_days=None, keyword=None,
        )
        assert [i["title"] for i in by_req["items"]] == ["任务一"]
        page1 = svc.list_tasks(
            db=db, user=world["member"], project_id=pid, requirement_id=None,
            assignee_id=None, status=None, cursor=None, limit=2,
            updated_within_days=None, keyword=None,
        )
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None
        page2 = svc.list_tasks(
            db=db, user=world["member"], project_id=pid, requirement_id=None,
            assignee_id=None, status=None, cursor=page1["next_cursor"], limit=2,
            updated_within_days=None, keyword=None,
        )
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

        def boom(statement, *args, **kwargs):
            # 仅模拟认领 UPDATE 遇锁;SELECT(短码寻址)放行
            if "UPDATE TASK" in str(statement).upper():
                raise OperationalError("UPDATE", {}, Exception("locked"))
            return real_execute(statement, *args, **kwargs)

        real_execute = db.execute
        monkeypatch.setattr(db, "execute", boom)
        with pytest.raises(AppError) as e:
            svc.claim_task(db, world["agent"], task)
        assert e.value.code == "conflict"


class TestRestoreEdges:
    def test_restore_missing_or_alive_task(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            svc.restore_task(db, world["admin"], "TASK-999")
        assert e.value.code == "not_found"
        task = make_task(db, world)["id"]
        with pytest.raises(AppError) as e:
            svc.restore_task(db, world["admin"], task)
        assert e.value.code == "not_found"
