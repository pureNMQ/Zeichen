"""状态机全路径 + 所有权 + 并发(服务层,API 与 MCP 共用同一 seam)。

- 需求六态 / 任务四态,完全自由流转(任意互转,直达终态,**无任何前置校验**)
- 自动流转已删除:任务状态变化不影响需求状态,需求状态全手动
- 取消便捷封装;已指派任务所有权;删除与恢复
"""

import threading
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.errors import AppError
from app.models import (
    Activity,
    Base,
    Project,
    ProjectMember,
    Requirement,
    Task,
    Team,
    User,
    WorkspaceMember,
)
from app.services import requirements as req_svc
from app.services import tasks as task_svc


@pytest.fixture()
def proj(db: Session, world: dict) -> dict:
    """world + carol(editor) + 带一个需求的项目。"""
    from app.tests.conftest import make_user

    carol = make_user(db, "carol", role="member")
    project = world["project"]
    db.add(ProjectMember(project_id=project.id, user_id=carol.id, role="editor"))
    db.commit()
    return {"**world": world, "carol": carol, "project": project, "req": None}


def make_requirement(db: Session, actor: User, project: Project, title="需求 A") -> Requirement:
    return req_svc.create_requirement(db, actor, project.id, title)


def make_requirement_row(db: Session, actor: User, project: Project, title="挂载需求") -> Requirement:
    return req_svc.create_requirement(db, actor, project.id, title)


def make_task(
    db: Session,
    actor: User,
    project: Project,
    title="任务 1",
    requirement_id=None,
    assignee_id=None,
) -> dict:
    # 任务必须挂已确认需求(ADR 0003);测试默认自动建一个
    if requirement_id is None:
        requirement = make_requirement_row(db, actor, project)
        req_svc.set_requirement_status(db, actor, requirement.code, "backlog")
    else:
        rid = requirement_id.code if hasattr(requirement_id, "code") else requirement_id
        requirement = req_svc.get_requirement(db, actor, rid)
        if requirement.status == "pending":
            req_svc.set_requirement_status(db, actor, requirement.code, "backlog")
    return task_svc.create_task(
        db, actor, project.id, title, None, requirement.code, assignee_id
    )


def _as_uuid(value) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)


def set_req(db, actor, rid, target):
    rid = rid.code if hasattr(rid, "code") else rid
    return req_svc.set_requirement_status(db, actor, rid, target)


def set_task(db, actor, tid, target):
    tid = tid.code if hasattr(tid, "code") else tid
    return task_svc.set_task_status(db, actor, tid, target)


class TestRequirementLifecycle:
    def test_create_pending_with_activity(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        assert r.status == "pending"
        activity = db.scalar(select(Activity).where(Activity.action == "create"))
        assert activity is not None
        assert activity.target_type == "requirement"

    def test_viewer_can_read_but_not_write(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        got = req_svc.get_requirement(db, world["member"], r.code)
        assert got.code == r.code
        with pytest.raises(AppError) as e:
            req_svc.update_requirement(db, world["member"], r.code, "hack", None)
        assert e.value.code == "permission_denied"

    def test_non_member_cannot_see(self, db: Session, world: dict, proj: dict):
        from app.tests.conftest import make_user

        stranger = make_user(db, "stranger", role="member")
        r = make_requirement(db, world["admin"], world["project"])
        with pytest.raises(AppError) as e:
            req_svc.get_requirement(db, stranger, r.code)
        assert e.value.code == "not_found"

    def test_free_transitions_all_pairs(self, db: Session, world: dict, proj: dict):
        """需求六态完全自由互转:每个源态可直达任意目标态(含终态,无前置校验)。"""
        statuses = ["pending", "backlog", "in_progress", "verifying", "done", "cancelled"]
        for current in statuses:
            r = make_requirement(db, world["admin"], world["project"], f"需求 {current}")
            rid = r
            if current != "pending":
                set_req(db, world["admin"], rid, current)
            for target in statuses:
                if target == current:
                    continue
                got = set_req(db, world["admin"], rid, target)
                assert got.status == target, f"{current} → {target} 失败"

    def test_same_status_conflict(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        with pytest.raises(AppError) as e:
            set_req(db, world["admin"], rid, "pending")
        assert e.value.code == "conflict"

    def test_invalid_status_rejected(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        with pytest.raises(AppError) as e:
            set_req(db, world["admin"], r.code, "nonsense")
        assert e.value.code == "invalid_request"

    def test_pending_requirement_rejects_task_derivation(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        with pytest.raises(AppError) as e:
            task_svc.create_task(
                db, world["admin"], world["project"].id, "过早拆解", None, r.code
            )
        assert e.value.code == "invalid_request"
        assert "请先确认需求" in e.value.message

    def test_done_with_pending_tasks_no_validation(self, db: Session, world: dict, proj: dict):
        """需求带未决任务可直接置 done:无任何前置校验(方案 B 完全自由)。"""
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        t = make_task(db, world["admin"], world["project"], "任务 1", rid)
        set_task(db, world["agent"], t.code, "in_progress")
        got = set_req(db, world["admin"], rid, "done")
        assert got.status == "done"
        # 继续加任务也不回退(无自动流转,状态全手动)
        make_task(db, world["admin"], world["project"], "新增任务", rid)
        assert req_svc.get_requirement(db, world["admin"], rid.code).status == "done"

    def test_task_status_does_not_touch_requirement(self, db: Session, world: dict, proj: dict):
        """任务状态变化不影响需求状态(自动流转已删除,需求状态全手动)。"""
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        t1 = make_task(db, world["admin"], world["project"], "任务 1", rid)
        t2 = make_task(db, world["admin"], world["project"], "任务 2", rid)
        set_task(db, world["agent"], t1.code, "in_progress")
        set_task(db, world["agent"], t1.code, "done")
        task_svc.cancel_task(db, world["admin"], t2.code)
        got = req_svc.get_requirement(db, world["admin"], rid.code)
        assert got.status == "backlog"

    def test_cancel_convenience(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        got = req_svc.cancel_requirement(db, world["admin"], rid.code)
        assert got.status == "cancelled"
        with pytest.raises(AppError) as e:
            req_svc.cancel_requirement(db, world["admin"], rid.code)
        assert e.value.code == "conflict"

    def test_status_activity_recorded(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        set_req(db, world["admin"], rid, "done")
        page = svc_list_activity(db, world["admin"], "requirement", rid.code)
        actions = [a["action"] for a in page["items"]]
        assert actions == ["create", "status"]

    def test_delete_requires_task_count_confirm(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        make_task(db, world["admin"], world["project"], "任务 1", rid)
        with pytest.raises(AppError) as e:
            req_svc.delete_requirement(db, world["admin"], rid.code)
        assert e.value.code == "conflict"
        with pytest.raises(AppError) as e:
            req_svc.delete_requirement(db, world["admin"], rid.code, confirm_task_count=3)
        assert e.value.code == "conflict"
        req_svc.delete_requirement(db, world["admin"], rid.code, confirm_task_count=1)
        with pytest.raises(AppError) as e:
            req_svc.get_requirement(db, world["admin"], rid.code)
        assert e.value.code == "not_found"

    def test_empty_requirement_delete_no_confirm_and_restore(self, db: Session, world: dict, proj: dict):
        r = make_requirement(db, world["admin"], world["project"])
        rid = r
        req_svc.delete_requirement(db, world["admin"], rid.code)
        restored = req_svc.restore_requirement(db, world["admin"], rid.code)
        assert restored.status == "pending"
        assert restored.deleted_at is None


class TestTaskStateMachine:
    def test_free_transitions_all_pairs(self, db: Session, world: dict, proj: dict):
        """任务四态完全自由互转(含直达 done/cancelled,无对话框语义)。"""
        statuses = ["backlog", "in_progress", "done", "cancelled"]
        for current in statuses:
            t = make_task(db, world["admin"], world["project"], f"任务 {current}")
            tid = t
            if current != "backlog":
                set_task(db, world["admin"], tid, current)
            for target in statuses:
                if target == current:
                    continue
                got = set_task(db, world["admin"], tid, target)
                assert got.status == target, f"{current} → {target} 失败"

    def test_direct_done_and_cancelled_no_ritual(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"])
        tid = t
        assert set_task(db, world["admin"], tid, "done").status == "done"
        t2 = make_task(db, world["admin"], world["project"], "任务 2")
        assert set_task(db, world["admin"], t2.code, "cancelled").status == "cancelled"

    def test_invalid_status_rejected(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"])
        with pytest.raises(AppError) as e:
            set_task(db, world["admin"], t.code, "nonsense")
        assert e.value.code == "invalid_request"

    def test_cancel_convenience(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"])
        got = task_svc.cancel_task(db, world["admin"], t.code)
        assert got.status == "cancelled"
        with pytest.raises(AppError) as e:
            task_svc.cancel_task(db, world["admin"], t.code)
        assert e.value.code == "conflict"

    def test_delete_assigned_task_restricted_then_restore(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"], assignee_id=world["agent"].id)
        tid = t
        with pytest.raises(AppError) as e:
            task_svc.delete_task(db, proj["carol"], tid.code)
        assert e.value.code == "permission_denied"
        task_svc.delete_task(db, world["agent"], tid.code)
        restored = task_svc.restore_task(db, world["admin"], tid.code)
        assert restored.deleted_at is None


class TestTaskOwnership:
    def test_set_status_by_assignee_only(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"], assignee_id=world["agent"].id)
        set_task(db, world["agent"], t.code, "in_progress")
        t2 = make_task(db, world["admin"], world["project"], "任务 2", assignee_id=world["agent"].id)
        with pytest.raises(AppError) as e:
            set_task(db, proj["carol"], t2.code, "in_progress")
        assert e.value.code == "permission_denied"
        set_task(db, world["admin"], t2.code, "in_progress")

    def test_unassigned_task_any_editor(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"])
        set_task(db, proj["carol"], t.code, "in_progress")

    def test_claim_then_second_claim_conflict(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"])
        claimed = task_svc.claim_task(db, world["agent"], t.code)
        assert claimed.assignee_id == world["agent"].id
        with pytest.raises(AppError) as e:
            task_svc.claim_task(db, proj["carol"], t.code)
        assert e.value.code == "conflict"

    def test_assign_unassigned_any_editor_then_reassign_restricted(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"])
        task_svc.assign_task(db, proj["carol"], t.code, world["agent"].id)
        with pytest.raises(AppError) as e:
            task_svc.assign_task(db, proj["carol"], t.code, proj["carol"].id)
        assert e.value.code == "permission_denied"
        task_svc.assign_task(db, world["admin"], t.code, proj["carol"].id)

    def test_unassign_by_assignee_or_admin(self, db: Session, world: dict, proj: dict):
        t = make_task(db, world["admin"], world["project"], assignee_id=world["agent"].id)
        task_svc.unassign_task(db, world["agent"], t.code)
        assert task_svc.get_task(db, world["admin"], t.code).assignee_id is None
        t2 = make_task(db, world["admin"], world["project"], "任务 2", assignee_id=world["agent"].id)
        with pytest.raises(AppError) as e:
            task_svc.unassign_task(db, proj["carol"], t2.code)
        assert e.value.code == "permission_denied"

    def test_requirement_status_any_editor(self, db: Session, world: dict, proj: dict):
        """需求改状态任意编辑权主体(无指派规则)。"""
        r = make_requirement(db, world["admin"], world["project"])
        got = set_req(db, proj["carol"], r.code, "in_progress")
        assert got.status == "in_progress"
        with pytest.raises(AppError) as e:
            set_req(db, world["member"], r.code, "done")
        assert e.value.code == "permission_denied"


class TestConcurrency:
    def test_claim_race_single_winner(self, tmp_path):
        """两线程并发认领同一任务:恰一人成功,另一人 conflict(文件库真实写竞争)。"""
        engine = create_engine(f"sqlite:///{tmp_path}/race.db", connect_args={"timeout": 1})
        Base.metadata.create_all(engine)
        sess = Session(engine)
        team = Team(name="贼船")
        sess.add(team)
        sess.flush()
        admin = User(username="admin", password_hash="", is_agent=False)
        sess.add(admin)
        sess.flush()
        sess.add(WorkspaceMember(team_id=team.id, user_id=admin.id, role="admin"))
        # ADR 0004:两个附属 agent 各随主人(项目 editor)参与认领竞争
        o1 = User(username="owner-1", password_hash="", is_agent=False)
        o2 = User(username="owner-2", password_hash="", is_agent=False)
        sess.add_all([o1, o2])
        sess.flush()
        sess.add_all(
            [
                WorkspaceMember(team_id=team.id, user_id=o1.id, role="member"),
                WorkspaceMember(team_id=team.id, user_id=o2.id, role="member"),
            ]
        )
        a1 = User(username="agent-1", password_hash="", is_agent=True, owner_id=o1.id)
        a2 = User(username="agent-2", password_hash="", is_agent=True, owner_id=o2.id)
        sess.add_all([a1, a2])
        sess.flush()
        project = Project(team_id=team.id, name="race")
        sess.add(project)
        sess.flush()
        requirement = Requirement(project_id=project.id, code="REQ-1", title="race req", status="backlog")
        sess.add(requirement)
        sess.flush()
        sess.add_all(
            [
                ProjectMember(project_id=project.id, user_id=o1.id, role="editor"),
                ProjectMember(project_id=project.id, user_id=o2.id, role="editor"),
            ]
        )
        task = Task(
            project_id=project.id,
            code="TASK-1",
            title="race task",
            status="backlog",
            created_by=admin.id,
            requirement_id="REQ-1",
        )
        sess.add(task)
        sess.commit()
        task_id = task.code

        barrier = threading.Barrier(2)
        outcomes = []

        def worker(user_id):
            local = sessionmaker(bind=engine, expire_on_commit=False)()
            barrier.wait()
            try:
                user = local.get(User, user_id)
                task_svc.claim_task(local, user, "TASK-1")
                outcomes.append(str(user_id))
            except AppError as e:
                outcomes.append(e.code)
            finally:
                local.close()

        threads = [threading.Thread(target=worker, args=(a1.id,)), threading.Thread(target=worker, args=(a2.id,))]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert len(outcomes) == 2
        winners = [o for o in outcomes if o != "conflict"]
        assert len(winners) == 1
        assert winners[0] in {str(a1.id), str(a2.id)}
        sess.close()
        engine.dispose()


def svc_list_activity(db, user, target_type, target_id):
    from app.services.polymorphic import list_activity

    return list_activity(db, user, target_type, target_id, None, 50)
