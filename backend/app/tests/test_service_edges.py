"""安全、分页、多态、通知、认证、成员、Agent 服务的补边测试。"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import ApiKey, PasswordSetupToken, Project, ProjectMember, User
from app.security import TokenError, decode_token, hash_password, token_digest, verify_password
from app.services import agents as agents_svc
from app.services import auth as auth_svc
from app.services import members as members_svc
from app.services import notifications as notif_svc
from app.services import pagination
from app.services import polymorphic as poly_svc
from app.tests.conftest import make_user


class TestSecurityEdges:
    def test_verify_password_guards(self):
        assert verify_password("x", "") is False
        assert verify_password("x", "not-a-valid-hash!!") is False
        stored = hash_password("good")
        assert verify_password("good", stored) is True
        assert verify_password("bad", stored) is False

    def test_decode_token_rejects_garbage(self):
        with pytest.raises(TokenError):
            decode_token("not-a-jwt")


class TestPaginationEdges:
    def test_encode_cursor_none_for_first_page(self):
        assert pagination.encode_cursor({"a": 1}, 0) is None
        assert pagination.encode_cursor({"a": 1}, -3) is None

    def test_decode_cursor_rejects_bad_offset(self):
        import base64
        import json

        filters = {"a": 1}
        cursor = pagination.encode_cursor(filters, 5)
        bad = base64.urlsafe_b64encode(
            json.dumps({"o": "five", "h": pagination._hash(filters)}).encode()
        ).decode()
        with pytest.raises(AppError) as e:
            pagination.decode_cursor(filters, bad)
        assert e.value.code == "invalid_request"
        assert pagination.decode_cursor(filters, cursor) == 5


class TestPolymorphicEdges:
    def test_resolve_target_for_project(self, db: Session, world: dict):
        project = poly_svc.resolve_target(db, "project", world["project"].id)
        assert project.id == world["project"].id
        with pytest.raises(AppError) as e:
            poly_svc.resolve_target(db, "project", uuid.uuid4())
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            poly_svc.resolve_target(db, "milestone", uuid.uuid4())
        assert e.value.code == "invalid_request"

    def test_comment_empty_body_and_missing_delete(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            poly_svc.create_comment(db, world["admin"], "requirement", world["project"].id, "   ")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            poly_svc.delete_comment(db, world["admin"], uuid.uuid4())
        assert e.value.code == "not_found"

    def test_reference_unsupported_type_and_missing_delete(self, db: Session, world: dict):
        from app.services import requirements as req_svc

        r = req_svc.create_requirement(db, world["admin"], world["project"].id, "需求")
        with pytest.raises(AppError) as e:
            poly_svc.create_reference(db, world["admin"], "requirement", r.code, "task", uuid.uuid4(), "teleports")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            poly_svc.delete_reference(db, world["admin"], uuid.uuid4())
        assert e.value.code == "not_found"

    def test_activity_actor_none_shows_system(self, db: Session, world: dict):
        from app.models import Activity

        activity = Activity(
            project_id=world["project"].id,
            target_type="project",
            target_id=str(world["project"].id),
            action="seed",
            summary="无操作者",
        )
        db.add(activity)
        db.commit()
        assert poly_svc._user_name(db, None) == "系统"
        assert poly_svc._activity_dict(db, activity)["actor"] == "系统"


class TestNotificationEdges:
    def test_notify_without_actor_is_noop(self, db: Session, world: dict):
        from app.models import Activity, Notification

        activity = Activity(
            project_id=world["project"].id,
            actor_id=None,
            target_type="project",
            target_id=str(world["project"].id),
            action="seed",
            summary="x",
        )
        db.add(activity)
        db.commit()
        notif_svc.notify_activity(db, activity)
        assert db.query(Notification).count() == 0

    def test_mark_read_and_mark_all(self, db: Session, world: dict):
        from app.models import Notification

        for i in range(2):
            db.add(
                Notification(
                    project_id=world["project"].id,
                    user_id=world["member"].id,
                    actor_id=world["admin"].id,
                    target_type="project",
                    target_id=str(world["project"].id),
                    action="note",
                    summary=f"n{i}",
                )
            )
        db.commit()
        assert notif_svc.unread_count(db, world["member"]) == 2
        first = db.query(Notification).first()
        notif_svc.mark_read(db, world["member"], first.id)
        assert notif_svc.unread_count(db, world["member"]) == 1
        with pytest.raises(AppError) as e:
            notif_svc.mark_read(db, world["member"], uuid.uuid4())
        assert e.value.code == "not_found"
        notif_svc.mark_all_read(db, world["member"])
        assert notif_svc.unread_count(db, world["member"]) == 0


class TestAuthEdges:
    def test_set_password_rejects_deleted_user(self, db: Session, world: dict):
        user = make_user(db, "ghost")
        user.deleted_at = datetime.now(timezone.utc)
        db.commit()
        with pytest.raises(AppError) as e:
            auth_svc.set_password(db, user.id, "new-pass-1")
        assert e.value.code == "unauthorized"

    def test_setup_token_rejects_agent_and_deleted_user(self, db: Session, world: dict):
        raw = members_svc._issue_password_setup_token(db, world["agent"])
        db.commit()
        with pytest.raises(AppError) as e:
            auth_svc.get_password_setup_user(db, raw)
        assert e.value.code == "unauthorized"
        user = make_user(db, "deleted-member")
        deleted_raw = members_svc._issue_password_setup_token(db, user)
        db.commit()
        user.deleted_at = datetime.now(timezone.utc)
        db.commit()
        with pytest.raises(AppError) as e:
            auth_svc.set_password_with_token(db, deleted_raw, "x")
        assert e.value.code == "unauthorized"
        with pytest.raises(AppError) as e:
            auth_svc.get_password_setup_user(db, deleted_raw)
        assert e.value.code == "unauthorized"

    def test_setup_token_consumed_only_once(self, db: Session, world: dict, monkeypatch):
        user = make_user(db, "once-member")
        raw = members_svc._issue_password_setup_token(db, user)
        db.commit()
        assert auth_svc.set_password_with_token(db, raw, "new-pass-1").username == "once-member"
        with pytest.raises(AppError) as e:
            auth_svc.set_password_with_token(db, raw, "again")
        assert e.value.code == "unauthorized"

    def test_setup_token_conditional_update_race(self, db: Session, world: dict, monkeypatch):
        user = make_user(db, "race-member")
        raw = members_svc._issue_password_setup_token(db, user)
        db.commit()

        class ZeroRow:
            rowcount = 0

        monkeypatch.setattr(db, "execute", lambda *a, **k: ZeroRow())
        with pytest.raises(AppError) as e:
            auth_svc.set_password_with_token(db, raw, "x")
        assert e.value.code == "unauthorized"


class TestMemberEdges:
    def test_create_member_invalid_role(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            members_svc.create_member(db, world["admin"], "newbie", "boss")
        assert e.value.code == "invalid_request"

    def test_regenerate_link_rejects_agent(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            members_svc.regenerate_password_setup_link(db, world["agent"].id)
        assert e.value.code == "invalid_request"

    def test_update_role_guards(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            members_svc.update_role(db, world["admin"], world["member"].id, "boss")
        assert e.value.code == "invalid_request"
        with pytest.raises(AppError) as e:
            members_svc.update_role(db, world["admin"], world["agent"].id, "member")
        assert e.value.code == "invalid_request"
        ghost = make_user(db, "ghost-member")
        ghost.deleted_at = datetime.now(timezone.utc)
        db.commit()
        with pytest.raises(AppError) as e:
            members_svc.update_role(db, world["admin"], ghost.id, "member")
        assert e.value.code == "not_found"
        outsider = make_user(db, "no-ws-member", role=None)
        with pytest.raises(AppError) as e:
            members_svc.update_role(db, world["admin"], outsider.id, "member")
        assert e.value.code == "not_found"

    def test_remove_member_without_membership(self, db: Session, world: dict):
        outsider = make_user(db, "no-ws-remove", role=None)
        with pytest.raises(AppError) as e:
            members_svc.remove_member(db, world["admin"], outsider.id)
        assert e.value.code == "not_found"


class TestAgentEdges:
    def test_update_agent_username_conflict(self, db: Session, world: dict):
        from app.services import agents as svc

        with pytest.raises(AppError) as e:
            svc.update_agent(db, world["admin"], world["agent"].id, username="bob")
        assert e.value.code == "conflict"

    def test_apply_grants_rejects_unknown_project(self, db: Session, world: dict):
        from app.services import agents as svc

        with pytest.raises(AppError) as e:
            svc.update_agent(
                db, world["admin"], world["agent"].id, grants=[{"project_id": uuid.uuid4(), "role": "editor"}]
            )
        assert e.value.code == "invalid_request"
        assert "项目不存在" in e.value.message

    def test_key_lookup_and_reveal_guards(self, db: Session, world: dict):
        from app.security import generate_api_token

        key, _ = agents_svc.issue_key(db, world["agent"].id, "note")
        assert agents_svc.list_keys(db, world["agent"].id)[0].id == key.id
        with pytest.raises(AppError) as e:
            agents_svc.reveal_key(db, world["admin"], "admin-pass-1", world["agent"].id, uuid.uuid4())
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            agents_svc.reveal_key(db, world["member"], "x", world["agent"].id, key.id)
        assert e.value.code == "permission_denied"
        with pytest.raises(AppError) as e:
            agents_svc.reveal_key(db, world["admin"], "wrong-pass", world["agent"].id, key.id)
        assert e.value.code == "permission_denied"
        revealed = agents_svc.reveal_key(db, world["admin"], "admin-pass-1", world["agent"].id, key.id)
        assert revealed.startswith("zc_")
