"""通知服务与 API 测试(规格书 §7.2 相关成员语义)。"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Notification
from app.services import notifications as svc
from app.services import requirements as req_svc
from app.services import tasks as task_svc
from app.tests.conftest import make_user


def make_requirement(db: Session, world: dict, title: str = "需求") -> dict:
    """由 agent(editor)创建需求,使 admin(owner) 成为通知接收者。"""
    req = req_svc.create_requirement(db, world["agent"], world["project"].id, title)
    req_svc.set_requirement_status(db, world["agent"], req.id, "backlog")
    return req_svc._requirement_dict(db, req)


class TestNotificationRelevantMembers:
    def test_actor_excluded_and_owner_notified(self, db: Session, world: dict):
        # agent 创建需求:admin 是 owner 收到通知,agent 自己不收
        r = make_requirement(db, world, "由 agent 创建")
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == world["admin"].id,
                Notification.target_id == uuid.UUID(r["id"]),
            )
        )
        assert n is not None
        assert n.action == "create"
        actor_notified = db.scalar(
            select(Notification).where(Notification.user_id == world["agent"].id)
        )
        assert actor_notified is None

    def test_assignee_notified(self, db: Session, world: dict):
        bob = world["member"]
        r = make_requirement(db, world)
        t = task_svc._task_dict(
            db,
            task_svc.create_task(
                db, world["admin"], world["project"].id, "指派任务", None,
                uuid.UUID(r["id"]), bob.id,
            ),
        )
        # bob 被指派,收到 create 通知(任务创建者 admin 是 owner 已收)
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == bob.id,
                Notification.target_id == uuid.UUID(t["id"]),
            )
        )
        assert n is not None
        assert n.target_type == "task"

    def test_comment_participant_notified_on_change(self, db: Session, world: dict):
        from sqlalchemy import update

        from app.models import ProjectMember
        from app.services import polymorphic as poly

        bob = world["member"]
        # bob 提升为 editor 以便评论
        db.execute(
            update(ProjectMember)
            .where(
                ProjectMember.project_id == world["project"].id,
                ProjectMember.user_id == bob.id,
            )
            .values(role="editor")
        )
        db.commit()
        # bob 评论需求
        r = make_requirement(db, world)
        poly.create_comment(db, bob, "requirement", uuid.UUID(r["id"]), "bob 参与")
        # 之后 admin 改状态,bob 应收到通知
        req_svc.set_requirement_status(db, world["admin"], uuid.UUID(r["id"]), "in_progress")
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == bob.id,
                Notification.target_id == uuid.UUID(r["id"]),
                Notification.action == "status",
            )
        )
        assert n is not None

    def test_viewer_receives_nothing_for_unrelated(self, db: Session, world: dict):
        # member 是 viewer,不是创建者/评论者/被指派者,需求变更不应通知
        r = make_requirement(db, world)
        req_svc.set_requirement_status(db, world["agent"], uuid.UUID(r["id"]), "in_progress")
        n = db.scalar(
            select(Notification).where(Notification.user_id == world["member"].id)
        )
        assert n is None

    def test_workspace_admin_notified_across_projects(self, db: Session, world: dict):
        other = world["project"]
        carol = make_user(db, "carol", role="admin")
        r = make_requirement(db, world)
        req_svc.set_requirement_status(db, world["agent"], uuid.UUID(r["id"]), "in_progress")
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == carol.id,
                Notification.target_id == uuid.UUID(r["id"]),
            )
        )
        assert n is not None


class TestNotificationApi:
    def test_unread_and_mark_read(self, db: Session, world: dict, client):
        make_requirement(db, world, "通知 API")
        # admin 登录查未读数
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        resp = client.get("/api/notifications/unread-count")
        assert resp.status_code == 200
        count = resp.json()["count"]
        assert count >= 1
        # 列表
        listing = client.get("/api/notifications")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert items
        # 标记一条已读
        nid = items[0]["id"]
        r = client.post(f"/api/notifications/{nid}/read")
        assert r.status_code == 200
        after = client.get("/api/notifications/unread-count").json()["count"]
        assert after == count - 1
        # 全部已读
        client.post("/api/notifications/read-all")
        assert client.get("/api/notifications/unread-count").json()["count"] == 0

    def test_unread_only_filter(self, db: Session, world: dict, client):
        from app.tests.conftest import login

        make_requirement(db, world, "只读未读")
        login(client, "admin", "admin-pass-1")
        listing = client.get("/api/notifications?unread_only=true")
        assert all(item["read"] is False for item in listing.json()["items"])
