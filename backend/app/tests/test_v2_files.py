import hashlib
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from app.api.files_v2 import _TransferLogFilter
from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import ApiKey, ProjectMember
from app.security import generate_api_token, token_digest
from app.tests.conftest import login
from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401
from app.v2 import files
from app.v2.file_models import FileGrant
from app.v2.file_storage import file_path

PNG = b"\x89PNG\r\n\x1a\nexample body"


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", str(tmp_path))
    return tmp_path


def _upload(client, base, name, content, request_id=None):
    return client.post(base, params={"name": name, "request_id": str(request_id or uuid4())}, content=content)


def _local_url(url: str) -> str:
    part = urlsplit(url)
    return f"{part.path}?{part.query}"


def test_web_upload_uses_immutable_bytes_and_keyset_library_paging(client, db, world, storage):
    login(client, "admin", "admin-pass-1")
    project_id = world["project"].id
    base = f"/api/v2/projects/{project_id}/files"
    request_id = uuid4()
    result = _upload(client, base, "测试图.png", iter((PNG[:8], PNG[8:])), request_id)
    assert result.status_code == 201, result.text
    first = result.json()
    assert first["media_type"] == "image/png"
    assert first["preview_href"].endswith("?inline=true")
    assert first["href"] == f"/projects/{project_id}/files/{first['id']}"
    assert _upload(client, base, "测试图.png", PNG, request_id).json() == first
    assert _upload(client, base, "测试图.png", b"different", request_id).status_code == 409

    second = _upload(client, base, "测试图.png", PNG).json()
    assert first["id"] != second["id"]
    filters = {"query": "测试", "images_only": "true", "limit": "1"}
    page1 = client.get(base, params=filters).json()
    page2 = client.get(base, params={**filters, "cursor": page1["next_cursor"]}).json()
    assert {page1["items"][0]["id"], page2["items"][0]["id"]} == {first["id"], second["id"]}
    assert page2["next_cursor"] is None
    wrong_filter = client.get(base, params={**filters, "query": "别的", "cursor": page1["next_cursor"]})
    assert wrong_filter.status_code == 400

    file_url = f"{base}/{first['id']}"
    assert client.patch(file_url, json={"name": "改名.png"}).json()["name"] == "改名.png"
    assert client.get(file_url).json()["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert client.delete(file_url).status_code == 200
    assert client.get(first["download_href"]).status_code == 404
    assert file_path(project_id, UUID(first["id"])).read_bytes() == PNG
    assert client.get(base, params={"state": "deleted"}).json()["items"][0]["id"] == first["id"]
    deleted = client.get(f"{file_url}/trash").json()
    assert deleted["deleted_by"] == str(world["admin"].id)
    assert deleted["download_href"] is None
    assert client.post(f"{file_url}/restore").json()["id"] == first["id"]
    assert client.get(first["download_href"]).content == PNG


def test_upload_bounds_include_trashed_bytes_and_clean_failed_stage(client, world, storage, monkeypatch):
    login(client, "admin", "admin-pass-1")
    config = get_settings()
    monkeypatch.setattr(config, "file_library_max_file_bytes", 5)
    monkeypatch.setattr(config, "file_library_project_quota_bytes", 6)
    base = f"/api/v2/projects/{world['project'].id}/files"
    assert _upload(client, base, "limit.txt", iter((b"123", b"456"))).status_code == 409
    assert list((storage / "library-v2" / ".staging").glob("*.part")) == []
    first = _upload(client, base, "first.txt", b"abcde").json()
    assert client.delete(f"{base}/{first['id']}").status_code == 200
    assert _upload(client, base, "quota.txt", b"12").status_code == 409
    assert client.get(base).json()["items"] == []


def test_read_grant_is_cookie_free_range_capable_and_rechecks_current_permission(client, db, world, storage, monkeypatch):
    login(client, "admin", "admin-pass-1")
    project_id, agent_id, owner_id = (world[k].id for k in ("project", "agent", "agent_owner"))
    base = f"/api/v2/projects/{project_id}/files"
    result = _upload(client, base, "file.png", PNG).json()
    other = _upload(client, base, "other.png", PNG).json()
    key = generate_api_token()
    key_row = ApiKey(user_id=agent_id, token_hash=token_digest(key))
    db.add(key_row)
    db.flush()
    file_id, key_id = UUID(result["id"]), key_row.id
    monkeypatch.setattr(get_settings(), "web_base_url", "https://example.test")
    grant = files.issue_read_grant(db, agent_id, project_id, file_id, api_key_id=key_id, inline=True)
    db.commit()
    assert grant["access_url"].startswith("https://example.test/")
    assert key not in grant["access_url"]
    url = _local_url(grant["access_url"])
    assert db.scalar(select(FileGrant.digest)) not in url

    with TestClient(app) as no_cookie:
        assert no_cookie.get(result["download_href"]).status_code == 401
        head = no_cookie.head(url)
        assert head.status_code == 200 and head.content == b""
        partial = no_cookie.get(url, headers={"Range": "bytes=0-7"})
        assert partial.status_code == 206 and partial.content == PNG[:8]
        assert partial.headers["Cache-Control"] == "private, no-store"
        assert no_cookie.get(url).content == PNG
        assert no_cookie.get(url.replace(result["id"], other["id"])).status_code == 404

        db.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == owner_id))
        db.commit()
        assert no_cookie.get(url).status_code == 404
        db.add(ProjectMember(project_id=project_id, user_id=owner_id, role="editor"))
        db.commit()
        db.execute(update(ApiKey).where(ApiKey.id == key_id).values(revoked_at=datetime.now(timezone.utc)))
        db.commit()
        assert no_cookie.get(url).status_code == 404


def test_grant_expiry_and_delete_do_not_reuse_previous_access(client, db, world, storage, monkeypatch):
    login(client, "admin", "admin-pass-1")
    project_id, actor_id = world["project"].id, world["admin"].id
    base = f"/api/v2/projects/{project_id}/files"
    file_id = UUID(_upload(client, base, "source.html", b"<script>example</script>").json()["id"])
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(files, "_now", lambda: now)
    grant = files.issue_read_grant(db, actor_id, project_id, file_id, api_key_id=None, inline=True)
    db.commit()
    with TestClient(app) as no_cookie:
        url = _local_url(grant["access_url"])
        response = no_cookie.get(url)
        assert response.headers["Content-Type"].startswith("text/plain")
        assert "sandbox" in response.headers["Content-Security-Policy"]
        monkeypatch.setattr(files, "_now", lambda: datetime(2030, 1, 1, 0, 15, tzinfo=timezone.utc))
        assert no_cookie.get(url).status_code == 404
        current = files.issue_read_grant(db, actor_id, project_id, file_id, api_key_id=None, inline=False)
        db.commit()
        file_url = f"{base}/{file_id}"
        assert client.delete(file_url).status_code == 200
        assert client.post(f"{file_url}/restore").status_code == 200
        assert no_cookie.get(_local_url(current["access_url"])).status_code == 404


def test_uvicorn_file_grant_access_log_excludes_query():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("localhost", "GET", "/api/v2/file-transfers/scope/id?grant=temporary", "1.1", 200), None)
    assert _TransferLogFilter().filter(record)
    assert "file-transfers/scope/id" in record.getMessage()
    assert "temporary" not in record.getMessage()


def test_mcp_file_grants_transfer_bytes_outside_tool_arguments(mcp_server, storage, monkeypatch):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    project_id = mcp_server["project_id"]
    monkeypatch.setattr(get_settings(), "attachment_storage_dir", mcp_server["storage"])
    db_path = mcp_server["log_file"].parent / "e2e.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread": False})

    def transfer_db():
        with Session(engine, expire_on_commit=False) as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, transfer_db)
    try:
        upload = client.call("files.prepare_upload", project_id=project_id, name="image.png", size=len(PNG))
        assert upload["method"] == "PUT" and upload["content_length"] == len(PNG)
        assert mcp_server["token"] not in upload["upload_url"]
        with TestClient(app) as no_cookie:
            upload_url = _local_url(upload["upload_url"])
            assert no_cookie.put(upload_url, content=PNG[:-1]).status_code == 400
            assert no_cookie.put(upload_url, content=PNG + b"x").status_code == 409
            uploaded = no_cookie.put(upload_url, content=iter((PNG[:8], PNG[8:])))
            assert uploaded.status_code == 201, uploaded.text
            row = uploaded.json()
            assert no_cookie.put(upload_url, content=PNG).json() == row
            assert no_cookie.put(upload_url, content=PNG[:-1] + b"x").status_code == 409
            grant = client.call("files.authorize_read", project_id=project_id, file_id=row["id"])
            assert grant["id"] == row["id"]
            assert "expires_at" in grant and "?grant=" in grant["access_url"]
            assert "content" not in grant and mcp_server["token"] not in grant["access_url"]
            assert no_cookie.get(_local_url(grant["access_url"])).content == PNG
            assert any(item["id"] == row["id"] for item in client.call("files.list", project_id=project_id)["items"])
            address = {"project_id": project_id, "file_id": row["id"]}
            assert client.call("files.get", **address)["sha256"] == hashlib.sha256(PNG).hexdigest()
            assert client.call("files.delete", **address)["deleted"] is True
            assert no_cookie.get(_local_url(grant["access_url"])).status_code == 404
            trashed = client.call("files.trash_list", project_id=project_id, query="image")["items"]
            assert [item["id"] for item in trashed] == [row["id"]]
            assert client.call("files.trash_get", **address)["deleted_by"] == mcp_server["agent_id"]
            assert client.call("files.restore", **address)["id"] == row["id"]
            assert no_cookie.get(_local_url(grant["access_url"])).status_code == 404
            reissued = client.call("files.authorize_read", **address)
            assert no_cookie.get(_local_url(reissued["access_url"])).content == PNG
    finally:
        engine.dispose()
