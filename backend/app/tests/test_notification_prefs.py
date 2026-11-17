"""通知偏好与实体级关注(REQ 023b607e)。"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Notification
from app.services import notifications as svc
from app.services import requirements as req_svc


def make_requirement(db: Session, world: dict, title: str = "需求") -> dict:
    req = req_svc.create_requirement(db, world["agent"], world["project"].id, title)
    req_svc.set_requirement_status(db, world["agent"], req.code, "backlog")
    return req_svc._requirement_dict(db, req)


def admin_notifications(db: Session, world: dict, target_id=None) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == world["admin"].id)
    if target_id is not None:
        stmt = stmt.where(Notification.target_id == target_id)
    return list(db.scalars(stmt).all())


class TestPreferences:
    def test_default_all_enabled(self, db: Session, world: dict):
        prefs = svc.get_preferences(db, world["admin"])
        assert all(prefs["domains"].values())
        assert all(prefs["actions"].values())

    def test_update_disables_and_unknown_rejected(self, db: Session, world: dict):
        prefs = svc.update_preferences(db, world["admin"], {"document": False}, {"status": False})
        assert prefs["domains"]["document"] is False
        assert prefs["actions"]["status"] is False
        # 显式开启(缺省态)会删除收窄行
        prefs = svc.update_preferences(db, world["admin"], {"document": True}, {"status": True})
        assert prefs["domains"]["document"] is True
        with pytest.raises(AppError):
            svc.update_preferences(db, world["admin"], {"nope": False}, {})

    def test_disabled_domain_suppresses(self, db: Session, world: dict):
        svc.update_preferences(db, world["admin"], {"requirement": False}, {"status": False})
        make_requirement(db, world, "静音需求")
        assert admin_notifications(db, world) == []

    def test_disabled_action_suppresses(self, db: Session, world: dict):
        svc.update_preferences(db, world["admin"], {}, {"create": False})
        make_requirement(db, world)
        creates = [n for n in admin_notifications(db, world) if n.action == "create"]
        assert creates == []


class TestWatch:
    def test_watch_unwatch_roundtrip(self, db: Session, world: dict):
        r = make_requirement(db, world)
        rid = r["id"]
        assert svc.is_watching(db, world["admin"], "requirement", rid) is False
        svc.watch_entity(db, world["admin"], "requirement", rid)
        assert svc.is_watching(db, world["admin"], "requirement", rid) is True
        svc.unwatch_entity(db, world["admin"], "requirement", rid)
        assert svc.is_watching(db, world["admin"], "requirement", rid) is False

    def test_viewer_can_watch(self, db: Session, world: dict):
        r = make_requirement(db, world)
        rid = r["id"]
        svc.watch_entity(db, world["member"], "requirement", rid)
        assert svc.is_watching(db, world["member"], "requirement", rid)

    def test_watch_does_not_generate_notifications_for_status_changes(self, db: Session, world: dict):
        svc.update_preferences(db, world["admin"], {"requirement": False}, {"status": False})
        r = make_requirement(db, world, "被关注需求")
        assert admin_notifications(db, world) == []
        svc.watch_entity(db, world["admin"], "requirement", r["id"])
        req_svc.set_requirement_status(db, world["agent"], r["id"], "in_progress")
        notes = admin_notifications(db, world, r["id"])
        assert notes == []


class TestWatchApiRoutes:
    """API 层回归:watch 三端点必须路由到 notifications 服务(REQ-50,曾误指 polymorphic 全 500)。"""

    def test_watch_roundtrip_via_http(self, client, world):
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        resp = client.post(
            f"/api/projects/{world['project'].id}/requirements",
            json={"title": "被关注需求"},
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]

        assert client.get(f"/api/targets/requirement/{rid}/watch").json() == {"watching": False}
        assert client.post(f"/api/targets/requirement/{rid}/watch").status_code == 201
        assert client.get(f"/api/targets/requirement/{rid}/watch").json() == {"watching": True}
        assert client.delete(f"/api/targets/requirement/{rid}/watch").status_code == 200
        assert client.get(f"/api/targets/requirement/{rid}/watch").json() == {"watching": False}

    def test_watch_uuid_target_project(self, client, world):
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        pid = str(world["project"].id)
        assert client.get(f"/api/targets/project/{pid}/watch").status_code == 200
        assert client.post(f"/api/targets/project/{pid}/watch").status_code == 201
        assert client.delete(f"/api/targets/project/{pid}/watch").status_code == 200
