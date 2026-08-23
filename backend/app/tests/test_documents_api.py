"""API reference module removal: endpoints are no longer exposed."""

import uuid

from app.tests.conftest import login


def test_code_reference_routes_are_removed(client, world):
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)
    sid = str(uuid.uuid4())

    assert client.get(f"/api/projects/{pid}/code-reference/libraries").status_code == 404
    assert client.post(f"/api/projects/{pid}/code-reference/libraries", json={}).status_code == 404
    assert client.get(f"/api/projects/{pid}/code-reference/tree").status_code == 404
    assert client.post(f"/api/code-reference/libraries/{sid}/symbols", json={}).status_code == 404
    assert client.patch(f"/api/code-reference/symbols/{sid}", json={}).status_code == 404
    assert client.post(f"/api/code-reference/symbols/{sid}/rollback", json={}).status_code == 404
