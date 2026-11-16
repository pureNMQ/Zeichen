"""需求与项目服务补边测试。"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Project, ProjectMember
from app.services import projects as proj_svc
from app.services import requirements as req_svc
from app.tests.conftest import make_user


class TestRequirementEdges:
    def test_update_title_validation(self, db: Session, world: dict):
        r = req_svc.create_requirement(db, world["admin"], world["project"].id, "标题")
        with pytest.raises(AppError) as e:
            req_svc.update_requirement(db, world["admin"], r.code, title="  ", description=None)
        assert e.value.code in ("invalid_request", "not_found")
        with pytest.raises(AppError) as e:
            req_svc.update_requirement(db, world["admin"], "REQ-999", title="x", description=None)
        assert e.value.code == "not_found"

    def test_list_status_filter(self, db: Session, world: dict):
        req_svc.create_requirement(db, world["admin"], world["project"].id, "待办需求")
        doing = req_svc.create_requirement(db, world["admin"], world["project"].id, "进行中需求")
        req_svc.set_requirement_status(db, world["admin"], doing.code, "in_progress")
        # 新签名(T1):status 多值(list[str] | None),新增 updated_within_days/keyword
        page = req_svc.list_requirements(
            db=db, user=world["member"], project_id=world["project"].id,
            status=["in_progress"], cursor=None, limit=20,
            updated_within_days=None, keyword=None,
        )
        assert [i["title"] for i in page["items"]] == ["进行中需求"]

    def test_restore_missing_or_alive(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            req_svc.restore_requirement(db, world["admin"], "REQ-999")
        assert e.value.code == "not_found"
        r = req_svc.create_requirement(db, world["admin"], world["project"].id, "活的")
        with pytest.raises(AppError) as e:
            req_svc.restore_requirement(db, world["admin"], r.code)
        assert e.value.code == "not_found"


class TestProjectEdges:
    def test_add_member_validation(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            proj_svc.add_project_member(db, world["admin"], world["project"].id, world["agent"].id, "dictator")
        assert e.value.code in ("invalid_request", "not_found")
        with pytest.raises(AppError) as e:
            proj_svc.add_project_member(db, world["admin"], world["project"].id, uuid.uuid4(), "editor")
        assert e.value.code == "not_found"
        outsider = make_user(db, "outsider2", role=None)
        with pytest.raises(AppError) as e:
            proj_svc.add_project_member(db, world["admin"], world["project"].id, outsider.id, "editor")
        assert e.value.code in ("invalid_request", "not_found")
        with pytest.raises(AppError) as e:
            proj_svc.add_project_member(db, world["admin"], world["project"].id, world["member"].id, "editor")
        assert e.value.code == "conflict"

    def test_update_role_validation(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            proj_svc.update_project_member_role(db, world["admin"], world["project"].id, world["member"].id, "boss")
        assert e.value.code in ("invalid_request", "not_found")

    def test_remove_missing_member(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            proj_svc.remove_project_member(db, world["admin"], world["project"].id, uuid.uuid4())
        assert e.value.code == "not_found"

    def test_transfer_owner_guards(self, db: Session, world: dict):
        with pytest.raises(AppError) as e:
            proj_svc.transfer_project_owner(
                db, world["agent"], world["project"].id, world["member"].id, "wrong"
            )
        assert e.value.code == "permission_denied"

    def test_transfer_owner_self_and_existing_owner(self, db: Session, world: dict):
        other = Project(team_id=world["team"].id, name="second")
        db.add(other)
        db.commit()
        db.add(ProjectMember(project_id=other.id, user_id=world["admin"].id, role="owner"))
        db.add(ProjectMember(project_id=other.id, user_id=world["member"].id, role="editor"))
        db.commit()
        with pytest.raises(AppError) as e:
            proj_svc.transfer_project_owner(
                db, world["admin"], other.id, world["admin"].id, "admin-pass-1"
            )
        assert e.value.code in ("invalid_request", "not_found")
        with pytest.raises(AppError) as e:
            proj_svc.transfer_project_owner(
                db, world["admin"], other.id, world["member"].id, "wrong-password"
            )
        assert e.value.code == "permission_denied"

    def test_transfer_owner_target_already_owner(self, db: Session, world: dict):
        other = Project(team_id=world["team"].id, name="second-owner")
        db.add(other)
        db.commit()
        db.add(ProjectMember(project_id=other.id, user_id=world["admin"].id, role="owner"))
        db.add(ProjectMember(project_id=other.id, user_id=world["member"].id, role="owner"))
        db.commit()
        with pytest.raises(AppError) as e:
            proj_svc.transfer_project_owner(
                db, world["admin"], other.id, world["member"].id, "admin-pass-1"
            )
        assert e.value.code == "conflict"

    def test_transfer_owner_flow(self, db: Session, world: dict):
        other = Project(team_id=world["team"].id, name="third")
        db.add(other)
        db.commit()
        db.add(ProjectMember(project_id=other.id, user_id=world["admin"].id, role="owner"))
        db.add(ProjectMember(project_id=other.id, user_id=world["member"].id, role="editor"))
        db.commit()
        proj_svc.transfer_project_owner(db, world["admin"], other.id, world["member"].id, "admin-pass-1")
        roles = {
            pm.user_id: pm.role
            for pm in db.query(ProjectMember).filter(ProjectMember.project_id == other.id).all()
        }
        assert roles[world["admin"].id] == "editor"
        assert roles[world["member"].id] == "owner"
