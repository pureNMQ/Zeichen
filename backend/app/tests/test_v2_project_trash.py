from app.models import ProjectMember, Requirement
from app.services import projects
from app.tests.conftest import login


def test_project_trash_restores_only_content_hidden_by_the_project(client, db, world):
    project_id = world["project"].id
    db.add_all([
        Requirement(project_id=project_id, code="REQ-1", title="active"),
        Requirement(
            project_id=project_id, code="REQ-2", title="independently deleted",
            deleted_at=world["project"].created_at,
        ),
    ])
    db.commit()
    login(client, "admin", "admin-pass-1")
    main_path = f"/api/projects/{project_id}"
    trash_path = f"/api/projects/trash/{project_id}"
    assert client.get(f"{main_path}/delete-impact").json()["affected"]["requirements"] == 1
    assert client.delete(main_path).status_code == 200
    assert client.get(main_path).status_code == 404
    assert client.get("/api/projects/trash", params={"q": "DEMO"}).json()["items"][0]["id"] == str(project_id)
    archived = client.get(trash_path).json()
    assert archived["deleted_by"] == str(world["admin"].id)
    assert archived["affected"]["requirements"] == 1

    assert client.post(f"{trash_path}/restore").json() == {"id": str(project_id), "restored": True}
    assert client.get(main_path).status_code == 200
    assert db.get(Requirement, (project_id, "REQ-2")).deleted_at is not None
    assert client.get(trash_path).status_code == 404


def test_project_trash_requires_current_owner_or_admin(db, world):
    project_id = world["project"].id
    projects.soft_delete_project(db, world["admin"], project_id)
    assert projects.list_deleted_projects(db, world["admin"])["items"][0]["id"] == str(project_id)
    assert projects.list_deleted_projects(db, world["member"])["items"] == []
    assert projects.list_deleted_projects(db, world["agent"])["items"] == []
    owner_grant = db.query(ProjectMember).filter_by(project_id=project_id, user_id=world["agent_owner"].id).one()
    owner_grant.role = "owner"
    db.commit()
    assert projects.list_deleted_projects(db, world["agent"])["items"][0]["id"] == str(project_id)
