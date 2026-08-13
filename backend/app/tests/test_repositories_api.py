"""Code repository registration API behavior."""

import uuid

from app.tests.conftest import login


def _login_admin(client):
    login(client, "admin", "admin-pass-1")


def _create(client, project_id: str, **overrides) -> dict:
    payload = {
        "name": "Backend",
        "vcs_type": "git",
        "url": "https://github.com/example/backend.git/",
        "description": "Primary service source",
        "default_branch": "main",
        **overrides,
    }
    response = client.post(f"/api/projects/{project_id}/repositories", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_list_update_delete_and_restore_repository(client, world):
    _login_admin(client)
    project_id = str(world["project"].id)
    repository = _create(client, project_id)
    assert repository["url"] == "https://github.com/example/backend.git/"
    assert repository["vcs_type"] == "git"

    listed = client.get(f"/api/projects/{project_id}/repositories")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["items"]] == [repository["id"]]

    updated = client.patch(f"/api/repositories/{repository['id']}", json={
        "name": "Backend source", "default_branch": "release",
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Backend source"
    assert updated.json()["default_branch"] == "release"

    assert client.post(f"/api/repositories/{repository['id']}/delete").status_code == 200
    assert client.get(f"/api/repositories/{repository['id']}").status_code == 404
    deleted = client.get(f"/api/projects/{project_id}/repositories/deleted")
    assert [row["id"] for row in deleted.json()["items"]] == [repository["id"]]
    restored = client.post(f"/api/repositories/{repository['id']}/restore")
    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None


def test_repository_vcs_validation_and_normalized_duplicate_guard(client, world):
    _login_admin(client)
    project_id = str(world["project"].id)
    _create(client, project_id)
    duplicate = client.post(f"/api/projects/{project_id}/repositories", json={
        "name": "Same remote", "vcs_type": "git", "url": "https://github.com/example/backend.git",
    })
    assert duplicate.status_code == 409

    missing_other_kind = client.post(f"/api/projects/{project_id}/repositories", json={
        "name": "Perforce", "vcs_type": "other", "url": "depot://main",
    })
    assert missing_other_kind.status_code == 400
    other = _create(client, project_id, name="Perforce", vcs_type="other", other_vcs_type="Perforce", url="depot://main")
    assert other["other_vcs_type"] == "Perforce"
    assert client.post(f"/api/projects/{project_id}/repositories", json={
        "name": "Bad svn", "vcs_type": "svn", "url": "git@host:repo",
    }).status_code == 400

    for url in ("https://user:pass@example.com/repo", "https://example.com/repo?token=secret", "ssh://git:pass@example.com/repo"):
        response = client.post(f"/api/projects/{project_id}/repositories", json={
            "name": f"Secret {url}", "vcs_type": "git", "url": url,
        })
        assert response.status_code == 400, response.text

    allowed_ssh = _create(client, project_id, name="SSH source", url="git@github.com:example/ssh-source.git")
    assert _create(client, project_id, name="SSH URI", url="ssh://git@github.com/example/ssh-uri.git")["url"].startswith("ssh://git@")
    switched = client.patch(f"/api/repositories/{allowed_ssh['id']}", json={"vcs_type": "svn", "url": "https://svn.example.com/project"})
    assert switched.status_code == 200, switched.text
    assert switched.json()["vcs_type"] == "svn"
    assert switched.json()["other_vcs_type"] is None

    other_to_git = client.patch(f"/api/repositories/{other['id']}", json={"vcs_type": "git", "url": "https://example.com/perforce-mirror.git"})
    assert other_to_git.status_code == 200, other_to_git.text
    assert other_to_git.json()["other_vcs_type"] is None


def test_repository_permissions_and_activity(client, db, world):
    from app.models import Activity
    from app.security import hash_password

    world["member"].password_hash = hash_password("bob-pass-1")
    db.commit()
    _login_admin(client)
    repository = _create(client, str(world["project"].id))
    assert db.query(Activity).filter_by(target_type="repository", target_id=uuid.UUID(repository["id"]), action="create").count() == 1

    login(client, "bob", "bob-pass-1")
    assert client.get(f"/api/projects/{world['project'].id}/repositories").status_code == 200
    assert client.get(f"/api/projects/{world['project'].id}/repositories/deleted").status_code == 403
    assert client.patch(f"/api/repositories/{repository['id']}", json={"name": "Cannot edit"}).status_code == 403
    assert client.post(f"/api/repositories/{repository['id']}/delete").status_code == 403


def test_repositories_are_polymorphic_targets(client, world):
    _login_admin(client)
    project_id = str(world["project"].id)
    repository = _create(client, project_id)
    comment = client.post(f"/api/targets/repository/{repository['id']}/comments", json={"body": "Tracked source"})
    assert comment.status_code == 201, comment.text
    assert client.get(f"/api/targets/repository/{repository['id']}/activity").status_code == 200
