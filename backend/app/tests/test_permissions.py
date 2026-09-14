"""权限服务补边测试(规格书 §5.1 两级角色判权)。"""

import pytest

from app.errors import AppError
from app.models import Project, ProjectMember, User, WorkspaceMember
from app.services import permissions as svc


def test_get_team_raises_conflict_before_bootstrap(db):
    with pytest.raises(AppError) as e:
        svc.get_team(db)
    assert e.value.code == "conflict"
    assert "首用户引导" in e.value.message


def test_workspace_member_lookup_roundtrip(db, world):
    assert svc.get_workspace_member(db, world["admin"].id).role == "admin"
    # ADR 0004:附属 agent 继承主人的工作区成员身份(carol=member)
    assert svc.get_workspace_member(db, world["agent"].id).role == "member"


def test_admin_implies_project_owner(db, world):
    assert svc.get_project_role(db, world["admin"].id, world["project"].id) == "owner"


def test_require_workspace_admin_enforces_role(db, world):
    svc.require_workspace_admin(db, world["admin"].id)
    with pytest.raises(AppError) as e:
        svc.require_workspace_admin(db, world["member"].id)
    assert e.value.code == "permission_denied"


def test_accessible_project_scopes_to_membership(db, world):
    project = svc.get_accessible_project(db, world["member"].id, world["project"].id, min_level="viewer")
    assert project.id == world["project"].id
    with pytest.raises(AppError) as e:
        svc.get_accessible_project(db, world["agent"].id, world["project"].id, min_level="owner")
    assert e.value.code == "permission_denied"


def test_accessible_project_hides_unknown_projects(db, world):
    with pytest.raises(AppError) as e:
        svc.get_accessible_project(db, world["member"].id, __import__("uuid").uuid4())
    assert e.value.code == "not_found"


def test_accessible_project_hides_deleted_projects(db, world):
    other = Project(team_id=world["team"].id, name="gone")
    db.add(other)
    db.commit()
    db.add(ProjectMember(project_id=other.id, user_id=world["member"].id, role="editor"))
    db.commit()
    other.deleted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    db.commit()
    with pytest.raises(AppError) as e:
        svc.get_accessible_project(db, world["member"].id, other.id)
    assert e.value.code == "not_found"


def test_require_project_role_returns_effective_role(db, world):
    assert svc.require_project_role(db, world["admin"].id, world["project"].id, "editor") == "owner"
    assert svc.require_project_role(db, world["agent"].id, world["project"].id, "editor") == "editor"
