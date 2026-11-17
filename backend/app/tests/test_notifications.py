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
    req_svc.set_requirement_status(db, world["agent"], req.code, "backlog")
    return req_svc._requirement_dict(db, req)


class TestNotificationRelevantMembers:
    def test_plain_creation_does_not_notify_owner_or_actor(self, db: Session, world: dict):
        r = make_requirement(db, world, "由 agent 创建")
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == world["admin"].id,
                Notification.target_id == r["id"],
            )
        )
        assert n is None
        actor_notified = db.scalar(
            select(Notification).where(Notification.user_id == world["agent"].id)
        )
        assert actor_notified is None

    def test_task_assignment_does_not_notify_assignee(self, db: Session, world: dict):
        bob = world["member"]
        r = make_requirement(db, world)
        t = task_svc._task_dict(
            db,
            task_svc.create_task(
                db, world["admin"], world["project"].id, "指派任务", None,
                r["id"], bob.id,
            ),
        )
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == bob.id,
                Notification.target_id == t["id"],
            )
        )
        assert n is None

    def test_state_change_does_not_notify_past_commenters(self, db: Session, world: dict):
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
        poly.create_comment(db, bob, "requirement", r["id"], "bob 参与")
        # 普通改状态没有产生新的显式提及或回复。
        req_svc.set_requirement_status(db, world["admin"], r["id"], "in_progress")
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == bob.id,
                Notification.target_id == r["id"],
                Notification.action == "status",
            )
        )
        assert n is None

    def test_viewer_receives_nothing_for_unrelated(self, db: Session, world: dict):
        # member 是 viewer,不是创建者/评论者/被指派者,需求变更不应通知
        r = make_requirement(db, world)
        req_svc.set_requirement_status(db, world["agent"], r["id"], "in_progress")
        n = db.scalar(
            select(Notification).where(Notification.user_id == world["member"].id)
        )
        assert n is None

    def test_workspace_admin_does_not_receive_routine_project_notifications(self, db: Session, world: dict):
        carol = make_user(db, "carol", role="admin")
        r = make_requirement(db, world)
        req_svc.set_requirement_status(db, world["agent"], r["id"], "in_progress")
        n = db.scalar(
            select(Notification).where(
                Notification.user_id == carol.id,
                Notification.target_id == r["id"],
            )
        )
        assert n is None


class TestNotificationApi:
    def test_unread_and_mark_read(self, db: Session, world: dict, client):
        row = make_requirement(db, world, "通知 API")
        db.add(Notification(project_id=world["project"].id, user_id=world["admin"].id,
                            target_type="requirement", target_id=row["id"], action="create"))
        db.commit()
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
