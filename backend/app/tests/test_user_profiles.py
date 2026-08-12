from pathlib import Path

from app.config import get_settings
from app.models import Attachment

from .conftest import login

PNG = b"\x89PNG\r\n\x1a\n" + b"avatar"


def test_user_profile_nickname_and_avatar_lifecycle(client, db, world, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", tmp_path)
    login(client, "admin", "admin-pass-1")

    updated = client.patch("/api/users/me", json={"nickname": "  船长  "})
    assert updated.status_code == 200
    assert updated.json()["nickname"] == "船长"
    assert updated.json()["display_name"] == "船长"
    assert updated.json()["avatar"] is None
    assert client.get("/api/auth/me").json()["display_name"] == "船长"

    uploaded = client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 200, uploaded.text
    avatar_url = uploaded.json()["avatar"]
    assert avatar_url.startswith(f"/api/users/{world['admin'].id}/avatar?v=")
    attachment = db.query(Attachment).filter_by(target_id=world["admin"].id).one()
    assert attachment.project_id is None
    assert Path(attachment.storage_path).read_bytes() == PNG

    downloaded = client.get(avatar_url)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.content == PNG

    removed = client.delete("/api/users/me/avatar")
    assert removed.status_code == 200
    assert removed.json()["avatar"] is None
    assert client.get(avatar_url).status_code == 404

    cleared = client.patch("/api/users/me", json={"nickname": "   "})
    assert cleared.json()["display_name"] == "admin"


def test_admin_can_manage_other_profiles_but_member_cannot(client, db, world, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", tmp_path)
    login(client, "admin", "admin-pass-1")
    member_id = world["member"].id
    response = client.patch(f"/api/users/{member_id}", json={"nickname": "Bob 昵称"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Bob 昵称"
    response = client.post(
        f"/api/users/{member_id}/avatar",
        files={"file": ("avatar.webp", b"RIFF\x04\x00\x00\x00WEBP", "image/webp")},
    )
    assert response.status_code == 200

    client.cookies.clear()
    world["member"].password_hash = world["admin"].password_hash
    db.commit()
    login(client, "bob", "admin-pass-1")
    assert client.patch(f"/api/users/{world['admin'].id}", json={"nickname": "no"}).status_code == 403
    assert client.delete(f"/api/users/{world['admin'].id}/avatar").status_code == 403


def test_avatar_validation_and_identity_payloads(client, db, world, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", tmp_path)
    login(client, "admin", "admin-pass-1")
    response = client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.txt", b"no", "text/plain")},
    )
    assert response.status_code == 400
    response = client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", b"not really a png", "image/png")},
    )
    assert response.status_code == 400

    world["member"].nickname = "小波"
    db.commit()
    members = client.get("/api/members").json()
    member = next(row for row in members if row["id"] == str(world["member"].id))
    assert member["display_name"] == "小波"
    assert member["avatar"] is None
