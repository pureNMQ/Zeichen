"""REQ-7 任务阻塞依赖:红灯用例(实现前编写,全部预期失败)。

契约(实现前已写入需求 197b5721 评论):

- 模型:新表 ``task_blocker``,模型 ``TaskBlocker`` 从 ``app.models`` 导出。
  边行字段:id / task_id(被阻塞任务,FK task.id CASCADE)/
  blocker_id(前置任务,FK task.id CASCADE)/ project_id / created_by / created_at;
  (task_id, blocker_id) 唯一(``uq_task_blocker_pair``);边行不软删,移除 = 删行。
- service:``app.services.task_blockers``
  - ``is_blocked(prerequisite_statuses)`` 纯函数:任一前置状态 != "done" → True
    (严格按需求:仅「已完成」解除阻塞,含 cancelled 在内的其余状态均视为受阻);
  - ``add_blocker(db, actor, task_id, blocker_id)`` 创建单条依赖;
  - ``set_blockers(db, actor, task_id, blocker_ids)`` 整体替换前置集合(编辑语义);
  - ``remove_blocker(db, actor, task_id, blocker_id)`` 移除单条(边不存在 → not_found);
  - ``list_blockers(db, user, task_id)`` 返回 {"blocked": bool,
    "items": [{"id","title","status","resolved"}]}(resolved = status == "done")。
  - 错误码:自依赖/跨项目 → invalid_request;重复依赖/循环依赖 → conflict;
    前置不存在或已软删 → not_found;viewer 维护 → permission_denied。
- 任务字典(``_task_dict``,列表与详情共用)新增:
  - ``blocked``: bool;``blocked_by``: 前置摘要列表 [{"id","title","status","resolved"}];
- API:TaskCreate / TaskUpdate 增加 ``blocked_by: list[uuid] | None``;
  PATCH 语义 = 整体替换(缺省 = 不变,[] = 清空)。
- MCP:tasks.create / tasks.update 支持 blocked_by,tasks.get / tasks.list 返回
  blocked 与 blocked_by,与 Web API 语义一致(见 test_task_blockers_mcp.py)。
- 软删契约:软删前置任务 = 依赖自动失效(视为已解除):不计入 blocked、
  不出现在 blocked_by 摘要;恢复前置后阻塞立即恢复。
- 状态机隔离:维护依赖不改变任务状态;状态变化不影响依赖;
  已完成任务增加前置只是信息,不自动改状态。
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Project, Task
from app.services import tasks as task_svc


def make_task(db: Session, world: dict, title="任务", **kw) -> Task:
    return task_svc.create_task(db, world["admin"], world["project"].id, title, **kw)


def svc_task_blockers():
    from app.services import task_blockers

    return task_blockers


# ---------- a) 数据模型(sqlite 建表后验证模型约束;迁移文件属实现,不在此跑) ----------


class TestTaskBlockerModel:
    def test_task_blocker_table_and_constraints(self, db: Session):
        """task_blocker 表存在:双 FK 指向 task、(task_id, blocker_id) 唯一、带项目五件套。"""
        from app.models import TaskBlocker

        assert TaskBlocker.__tablename__ == "task_blocker"
        cols = {c.name for c in TaskBlocker.__table__.columns}
        assert {"id", "task_id", "blocker_id", "project_id", "created_by", "created_at"} <= cols
        fk_targets = {fk.target_fullname for fk in TaskBlocker.__table__.foreign_keys}
        assert "task.id" in fk_targets
        pair_unique = [
            u for u in TaskBlocker.__table__.constraints if u.name == "uq_task_blocker_pair"
        ]
        assert pair_unique, "缺少 (task_id, blocker_id) 唯一约束 uq_task_blocker_pair"

    def test_blocker_row_roundtrip_and_duplicate_rejected(self, db: Session, world: dict):
        from app.models import TaskBlocker

        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        db.add(TaskBlocker(task_id=a.id, blocker_id=b.id, project_id=a.project_id))
        db.flush()
        rows = db.query(TaskBlocker).all()
        assert len(rows) == 1 and rows[0].task_id == a.id and rows[0].blocker_id == b.id
        db.add(TaskBlocker(task_id=a.id, blocker_id=b.id, project_id=a.project_id))
        with pytest.raises(IntegrityError):
            db.flush()


# ---------- c) 阻塞语义:纯函数级 ----------


class TestBlockSemanticsPureFunction:
    def test_is_blocked_only_done_resolves(self):
        """任一前置非 done → 受阻;全部 done → 解除;空集合 → 未受阻。"""
        is_blocked = svc_task_blockers().is_blocked
        assert is_blocked([]) is False
        assert is_blocked(["done"]) is False
        assert is_blocked(["done", "done"]) is False
        for status in ("backlog", "in_progress", "verifying", "cancelled"):
            assert is_blocked([status]) is True, status
        assert is_blocked(["done", "backlog"]) is True


# ---------- b) 依赖 CRUD(service 层) ----------


class TestAddBlocker:
    def test_add_blocker_same_project_succeeds(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        state = list_blockers(db, world["admin"], a.id)
        assert state["blocked"] is True
        assert [i["id"] for i in state["items"]] == [b.id]
        assert state["items"][0]["title"] == "任务B"
        assert state["items"][0]["status"] == "backlog"
        assert state["items"][0]["resolved"] is False

    def test_add_blocker_rejects_self_dependency(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "任务A")
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], a.id, a.id)
        assert e.value.code == "invalid_request"

    def test_add_blocker_rejects_cross_project(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "任务A")
        other = Project(team_id=world["team"].id, name="其他项目")
        db.add(other)
        db.commit()
        from app.services import tasks as svc

        foreign = svc.create_task(db, world["admin"], other.id, "别项目的任务")
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], a.id, foreign.id)
        assert e.value.code == "invalid_request"

    def test_add_blocker_rejects_duplicate(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], a.id, b.id)
        assert e.value.code == "conflict"

    def test_add_blocker_rejects_two_node_cycle(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], b.id, a.id)
        assert e.value.code == "conflict"

    def test_add_blocker_rejects_long_chain_cycle(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "A")
        b = make_task(db, world, "B")
        c = make_task(db, world, "C")
        d = make_task(db, world, "D")
        add_blocker(db, world["admin"], a.id, b.id)
        add_blocker(db, world["admin"], b.id, c.id)
        add_blocker(db, world["admin"], c.id, d.id)
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], d.id, a.id)
        assert e.value.code == "conflict"

    def test_add_blocker_missing_or_deleted_blocker_not_found(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "任务A")
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], a.id, uuid.uuid4())
        assert e.value.code == "not_found"
        b = make_task(db, world, "待删除前置")
        task_svc.delete_task(db, world["admin"], b.id)
        with pytest.raises(AppError) as e:
            add_blocker(db, world["admin"], a.id, b.id)
        assert e.value.code == "not_found"

    def test_viewer_cannot_maintain_blockers(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        with pytest.raises(AppError) as e:
            add_blocker(db, world["member"], a.id, b.id)
        assert e.value.code == "permission_denied"


class TestSetBlockers:
    def test_set_blockers_replaces_set(self, db: Session, world: dict):
        set_blockers = svc_task_blockers().set_blockers
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        c = make_task(db, world, "任务C")
        set_blockers(db, world["admin"], a.id, [b.id])
        set_blockers(db, world["admin"], a.id, [b.id, c.id])
        state = list_blockers(db, world["admin"], a.id)
        assert {i["id"] for i in state["items"]} == {b.id, c.id}
        set_blockers(db, world["admin"], a.id, [c.id])
        state = list_blockers(db, world["admin"], a.id)
        assert [i["id"] for i in state["items"]] == [c.id]
        set_blockers(db, world["admin"], a.id, [])
        state = list_blockers(db, world["admin"], a.id)
        assert state["blocked"] is False and state["items"] == []

    def test_set_blockers_validates_rules(self, db: Session, world: dict):
        set_blockers = svc_task_blockers().set_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        with pytest.raises(AppError) as e:
            set_blockers(db, world["admin"], a.id, [a.id])
        assert e.value.code == "invalid_request"
        set_blockers(db, world["admin"], a.id, [b.id])
        with pytest.raises(AppError) as e:
            set_blockers(db, world["admin"], b.id, [a.id])
        assert e.value.code == "conflict"


class TestRemoveBlocker:
    def test_remove_blocker(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        remove_blocker = svc_task_blockers().remove_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        remove_blocker(db, world["admin"], a.id, b.id)
        state = list_blockers(db, world["admin"], a.id)
        assert state["blocked"] is False and state["items"] == []
        with pytest.raises(AppError) as e:
            remove_blocker(db, world["admin"], a.id, b.id)
        assert e.value.code == "not_found"


class TestListBlockersResolvedState:
    def test_list_blockers_reports_status_and_resolved(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        task_svc.set_task_status(db, world["admin"], b.id, "done")
        state = list_blockers(db, world["admin"], a.id)
        assert state["blocked"] is False
        assert state["items"][0]["id"] == b.id
        assert state["items"][0]["status"] == "done"
        assert state["items"][0]["resolved"] is True


# ---------- 软删契约:软删前置 = 依赖自动失效 ----------


class TestSoftDeletedBlockerContract:
    def test_soft_deleted_blocker_unblocks_and_restore_resumes(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "前置任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        assert list_blockers(db, world["admin"], a.id)["blocked"] is True

        task_svc.delete_task(db, world["admin"], b.id)
        state = list_blockers(db, world["admin"], a.id)
        assert state["blocked"] is False
        assert all(i["id"] != b.id for i in state["items"])

        task_svc.restore_task(db, world["admin"], b.id)
        state = list_blockers(db, world["admin"], a.id)
        assert state["blocked"] is True
        assert [i["id"] for i in state["items"]] == [b.id]


# ---------- g) 状态机隔离 ----------


class TestStateMachineIsolation:
    def test_dependency_ops_do_not_change_status(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        remove_blocker = svc_task_blockers().remove_blocker
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        task_svc.set_task_status(db, world["admin"], a.id, "in_progress")
        add_blocker(db, world["admin"], a.id, b.id)
        db.refresh(a)
        assert a.status == "in_progress"
        remove_blocker(db, world["admin"], a.id, b.id)
        db.refresh(a)
        assert a.status == "in_progress"

    def test_status_change_does_not_touch_blockers(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        add_blocker(db, world["admin"], a.id, b.id)
        for target in ("in_progress", "verifying", "backlog"):
            task_svc.set_task_status(db, world["admin"], a.id, target)
            state = list_blockers(db, world["admin"], a.id)
            assert [i["id"] for i in state["items"]] == [b.id]

    def test_blocker_completion_does_not_change_blocked_task_status(self, db: Session, world: dict):
        add_blocker = svc_task_blockers().add_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        task_svc.set_task_status(db, world["admin"], a.id, "in_progress")
        add_blocker(db, world["admin"], a.id, b.id)
        task_svc.set_task_status(db, world["admin"], b.id, "done")
        db.refresh(a)
        assert a.status == "in_progress"
        assert list_blockers(db, world["admin"], a.id)["blocked"] is False

    def test_done_task_gaining_blockers_stays_done(self, db: Session, world: dict):
        """已完成任务的前置变化仍只是信息:不自动改状态,仅 blocked 提示为真。"""
        add_blocker = svc_task_blockers().add_blocker
        list_blockers = svc_task_blockers().list_blockers
        a = make_task(db, world, "任务A")
        b = make_task(db, world, "任务B")
        task_svc.set_task_status(db, world["admin"], a.id, "done")
        add_blocker(db, world["admin"], a.id, b.id)
        db.refresh(a)
        assert a.status == "done"
        assert list_blockers(db, world["admin"], a.id)["blocked"] is True


# ---------- d) API 层 ----------


class TestTaskBlockerApi:
    def _create(self, client, project_id, title, blocked_by=None):
        payload: dict = {"title": title}
        if blocked_by is not None:
            payload["blocked_by"] = [str(x) for x in blocked_by]
        return client.post(f"/api/projects/{project_id}/tasks", json=payload)

    def test_create_task_with_blocked_by_returns_block_state(
        self, client, db: Session, world: dict
    ):
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        pid = world["project"].id
        blocker = self._create(client, pid, "前置任务").json()
        resp = self._create(client, pid, "被阻塞任务", blocked_by=[blocker["id"]])
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["blocked"] is True
        assert [i["id"] for i in body["blocked_by"]] == [blocker["id"]]

    def test_patch_blocked_by_replaces_and_clears(self, client, db: Session, world: dict):
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        pid = world["project"].id
        b1 = self._create(client, pid, "前置一").json()
        b2 = self._create(client, pid, "前置二").json()
        task = self._create(client, pid, "主任务").json()

        resp = client.patch(f"/api/tasks/{task['id']}", json={"blocked_by": [b1["id"]]})
        assert resp.status_code == 200, resp.text
        assert [i["id"] for i in resp.json()["blocked_by"]] == [b1["id"]]

        resp = client.patch(f"/api/tasks/{task['id']}", json={"blocked_by": [b1["id"], b2["id"]]})
        assert {i["id"] for i in resp.json()["blocked_by"]} == {b1["id"], b2["id"]}

        resp = client.patch(f"/api/tasks/{task['id']}", json={"blocked_by": []})
        assert resp.json()["blocked"] is False and resp.json()["blocked_by"] == []

    def test_task_detail_returns_blocked_and_summaries(self, client, db: Session, world: dict):
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        pid = world["project"].id
        blocker = self._create(client, pid, "前置任务").json()
        task = self._create(client, pid, "主任务", blocked_by=[blocker["id"]]).json()
        resp = client.get(f"/api/tasks/{task['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["blocked"] is True
        summary = body["blocked_by"][0]
        assert summary["id"] == blocker["id"]
        assert summary["title"] == "前置任务"
        assert summary["status"] == "backlog"
        assert summary["resolved"] is False

    def test_viewer_reads_block_state_but_cannot_maintain(
        self, client, db: Session, world: dict
    ):
        from app.tests.conftest import login, make_user

        from app.models import ProjectMember

        viewer = make_user(db, "viewer-v", role="member", with_password="viewer-pass-1")
        db.add(ProjectMember(project_id=world["project"].id, user_id=viewer.id, role="viewer"))
        db.commit()

        login(client, "admin", "admin-pass-1")
        pid = world["project"].id
        blocker = self._create(client, pid, "前置任务").json()
        task = self._create(client, pid, "主任务", blocked_by=[blocker["id"]]).json()

        client.post("/api/auth/logout")
        login(client, "viewer-v", "viewer-pass-1")
        resp = client.get(f"/api/tasks/{task['id']}")
        assert resp.status_code == 200
        assert resp.json()["blocked"] is True
        resp = client.patch(f"/api/tasks/{task['id']}", json={"blocked_by": []})
        assert resp.status_code == 403
        assert resp.json()["code"] == "permission_denied"
