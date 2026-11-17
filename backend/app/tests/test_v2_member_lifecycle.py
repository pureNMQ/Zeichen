from app.config import get_settings
from app.models import ProjectMember
from app.tests.conftest import login


def test_reactivate_member_requires_fresh_session_and_does_not_restore_grants(client, db, world):
    username = world["member"].username
    member_id = world["member"].id
    cookie_name = get_settings().session_cookie_name
    login(client, username, "temporary-fixture")
    assert client.post("/api/auth/set-password", json={"password": "new-member-password"}).status_code == 200
    previous_session = client.cookies.get(cookie_name)
    assert client.get("/api/members/inactive").status_code == 403
    login(client, "admin", "admin-pass-1")
    assert client.delete(f"/api/members/{member_id}").status_code == 200
    assert [item["id"] for item in client.get("/api/members/inactive").json()] == [str(member_id)]
    activated = client.post(f"/api/members/inactive/{member_id}/reactivate").json()
    assert activated["id"] == str(member_id)
    assert activated["role"] == "member"
    assert activated["password_setup_url"] is None
    assert db.query(ProjectMember).filter_by(user_id=member_id).count() == 0
    client.cookies.clear()
    client.cookies.set(cookie_name, previous_session)
    assert client.get("/api/auth/me").status_code == 401
    login(client, username, "new-member-password")
    assert client.get("/api/auth/me").json()["id"] == str(member_id)
