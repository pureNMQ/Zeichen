"""comment / activity / reference 多态服务测试。"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Activity, Comment, Project, ProjectMember, Reference, User
from app.services import polymorphic as svc
from app.services import requirements as req_svc
from app.tests.conftest import make_user


@pytest.fixture()
def proj(db: Session, world: dict) -> dict:
    carol = make_user(db, "carol", role="member")
    db.add(ProjectMember(project_id=world["project"].id, user_id=carol.id, role="editor"))
    db.commit()
    return {"carol": carol, "project": world["project"], "world": world}


def make_requirement(db: Session, world: dict) -> dict:
    return req_svc._requirement_dict(
        db, req_svc.create_requirement(db, world["admin"], world["project"].id, "需求")
    )


class TestComment:
    def test_create_list_delete_own(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world)
        rid = uuid.UUID(r["id"])
        svc.create_comment(db, world["agent"], "requirement", rid, "agent 评论")
        svc.create_comment(db, world["admin"], "requirement", rid, "admin 评论")
        page = svc.list_comments(db, world["member"], "requirement", rid, None, 20)
        assert len(page["items"]) == 2
        assert page["items"][0]["author"] == "agent-a"
        # viewer 不能写
        with pytest.raises(AppError) as e:
            svc.create_comment(db, world["member"], "requirement", rid, "不该写")
        assert e.value.code == "permission_denied"
        # 他人评论,editor 不能删
        c = page["items"][0]
        with pytest.raises(AppError) as e:
            svc.delete_comment(db, proj["carol"], uuid.UUID(c["id"]))
        assert e.value.code == "permission_denied"
        # 作者可删
        svc.delete_comment(db, world["agent"], uuid.UUID(c["id"]))
        page2 = svc.list_comments(db, world["member"], "requirement", rid, None, 20)
        assert len(page2["items"]) == 1

    def test_owner_or_admin_can_delete_any(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world)
        rid = uuid.UUID(r["id"])
        svc.create_comment(db, world["agent"], "requirement", rid, "谁的")
        page = svc.list_comments(db, world["admin"], "requirement", rid, None, 20)
        svc.delete_comment(db, world["admin"], uuid.UUID(page["items"][0]["id"]))
        page2 = svc.list_comments(db, world["admin"], "requirement", rid, None, 20)
        assert page2["items"] == []

    def test_comment_on_user_target_rejected(self, db: Session, world: dict, proj: dict):
        with pytest.raises(AppError) as e:
            svc.create_comment(db, world["admin"], "user", world["admin"].id, "hi")
        assert e.value.code == "invalid_request"

    def test_comment_on_missing_target_not_found(self, db: Session, world: dict, proj: dict):
        with pytest.raises(AppError) as e:
            svc.create_comment(db, world["admin"], "requirement", uuid.uuid4(), "hi")
        assert e.value.code == "not_found"


class TestActivity:
    def test_actions_recorded_with_actor(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world)
        rid = uuid.UUID(r["id"])
        from app.services import tasks as task_svc

        t = task_svc._task_dict(
            db, task_svc.create_task(db, world["admin"], world["project"].id, "任务", None, rid)
        )
        task_svc.set_task_status(db, world["agent"], uuid.UUID(t["id"]), "in_progress")
        page = svc.list_activity(db, world["member"], "requirement", rid, None, 50)
        assert [a["action"] for a in page["items"]] == ["create"]
        task_page = svc.list_activity(db, world["member"], "task", uuid.UUID(t["id"]), None, 50)
        actions = [(a["action"], a["actor"]) for a in task_page["items"]]
        assert ("create", "admin") in actions
        assert ("status", "agent-a") in actions

    def test_activity_immutable_append(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world)
        rid = uuid.UUID(r["id"])
        svc.record_activity(db, world["project"].id, world["admin"].id, "requirement", rid, "test")
        db.commit()
        activity = db.scalar(select(Activity).where(Activity.action == "test"))
        assert activity.created_at is not None
        assert not hasattr(activity, "updated_at")


class TestReference:
    def test_create_dup_and_bidirectional_list(self, db: Session, world: dict, proj: dict):
        r1 = make_requirement(db, world)
        r2 = make_requirement(db, world)
        i1, i2 = uuid.UUID(r1["id"]), uuid.UUID(r2["id"])
        svc.create_reference(db, world["admin"], "requirement", i1, "requirement", i2, "derives")
        with pytest.raises(AppError) as e:
            svc.create_reference(db, world["admin"], "requirement", i1, "requirement", i2, "derives")
        assert e.value.code == "conflict"
        from_side = svc.list_references(db, world["member"], "requirement", i1, None, 20)
        to_side = svc.list_references(db, world["member"], "requirement", i2, None, 20)
        assert len(from_side["items"]) == 1
        assert len(to_side["items"]) == 1
        assert to_side["items"][0]["from_id"] == str(i1)

    def test_cross_project_and_self_rejected(self, db: Session, world: dict, proj: dict):
        r1 = make_requirement(db, world)
        i1 = uuid.UUID(r1["id"])
        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        r2 = req_svc.create_requirement(db, world["admin"], other.id, "别的项目需求")
        with pytest.raises(AppError) as e:
            svc.create_reference(db, world["admin"], "requirement", i1, "requirement", r2.id, "mentions")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            svc.create_reference(db, world["admin"], "requirement", i1, "requirement", i1, "mentions")
        assert e.value.code == "invalid_request"

    def test_delete_reference(self, db: Session, world: dict, proj: dict):
        r1 = make_requirement(db, world)
        r2 = make_requirement(db, world)
        ref = svc.create_reference(
            db, world["admin"], "requirement", uuid.UUID(r1["id"]), "requirement", uuid.UUID(r2["id"]), "documents"
        )
        svc.delete_reference(db, world["agent"], ref.id)
        page = svc.list_references(db, world["member"], "requirement", uuid.UUID(r1["id"]), None, 20)
        assert page["items"] == []
