"""附件服务与 API 测试(规格书 §4.2 / §8.2 配额)。"""

import os
import uuid

import pytest
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Attachment, Project
from app.services import attachments as svc
from app.services import requirements as req_svc
from app.services import tasks as task_svc


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "attachment_storage_dir", str(tmp_path / "attachments"))
    monkeypatch.setattr(get_settings(), "attachment_max_file_bytes", 4096)
    monkeypatch.setattr(get_settings(), "attachment_project_quota_bytes", 6000)
    yield


def make_requirement(db: Session, world: dict) -> dict:
    return req_svc._requirement_dict(
        db, req_svc.create_requirement(db, world["admin"], world["project"].id, "带附件的需求")
    )


class TestAttachmentService:
    def test_upload_and_download(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        rid = r["id"]
        a = svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "note.txt", b"hello")
        assert a.size == 5
        file_name, data, _ = svc.download(db, world["member"], a.id)
        assert file_name == "note.txt"
        assert data == b"hello"
        # 文件真实落盘
        path = svc._attachment_path(a.project_id, a.id)
        assert path.is_file()

    def test_upload_permission_viewer_denied(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        with pytest.raises(AppError) as e:
            svc.upload(db, world["member"], world["project"].id, "requirement", r["id"], "a.txt", b"x")
        assert e.value.code == "permission_denied"

    def test_empty_file_rejected(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "empty.bin", b"")
        assert e.value.code == "invalid_request"

    def test_max_file_size_conflict(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "big.bin", b"x" * 8000)
        assert e.value.code == "conflict"

    def test_project_quota_conflict(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        rid = r["id"]
        svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "a.bin", b"x" * 3000)
        # 配额 6000,已用 3000,再传 4000 超限
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "b.bin", b"y" * 4000)
        assert e.value.code == "conflict"

    def test_cross_project_target_rejected(self, db: Session, world: dict, isolated_storage):
        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        r = req_svc._requirement_dict(
            db, req_svc.create_requirement(db, world["admin"], other.id, "别的项目")
        )
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "a.txt", b"x")
        # 他项目同码在本项目内寻址不存在 → not_found(ADR 0002 项目内短码)
        assert e.value.code == "not_found"

    def test_list_and_delete_restore(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        rid = r["id"]
        svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "one.txt", b"1")
        svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "two.txt", b"22")
        page = svc.list_attachments(db, world["member"], "requirement", rid, None, 20)
        assert len(page["items"]) == 2
        aid = uuid.UUID(page["items"][0]["id"])
        svc.soft_delete(db, world["admin"], aid)
        remaining = svc.list_attachments(db, world["member"], "requirement", rid, None, 20)
        assert len(remaining["items"]) == 1
        svc.restore(db, world["admin"], aid)
        assert len(svc.list_attachments(db, world["member"], "requirement", rid, None, 20)["items"]) == 2

    def test_same_requirement_code_separates_project_lists_and_cursors(self, db: Session, world: dict):
        project = world["project"]
        other = Project(team_id=world["team"].id, name="other")
        db.add(other)
        db.commit()
        rid = make_requirement(db, world)["id"]
        other_req = req_svc.create_requirement(db, world["admin"], other.id, "另一个项目的需求")
        assert other_req.code == rid
        for name in ["one.txt", "two.txt"]:
            svc.upload(db, world["agent"], project.id, "requirement", rid, name, b"x")
        svc.upload(db, world["admin"], other.id, "requirement", rid, "unrelated.txt", b"y")

        first_page = svc.list_attachments(db, world["member"], "requirement", rid, None, 1, project.id)
        assert first_page["next_cursor"]
        second_page = svc.list_attachments(
            db, world["member"], "requirement", rid, first_page["next_cursor"], 1, project.id
        )
        assert {item["file_name"] for item in first_page["items"] + second_page["items"]} == {"one.txt", "two.txt"}
        with pytest.raises(AppError) as error:
            svc.list_attachments(db, world["admin"], "requirement", rid, first_page["next_cursor"], 1, other.id)
        assert error.value.code == "invalid_request"
        other_page = svc.list_attachments(db, world["admin"], "requirement", rid, None, 20, other.id)
        assert [item["file_name"] for item in other_page["items"]] == ["unrelated.txt"]

    def test_delete_follows_parent(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        rid = r["id"]
        svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "doc.pdf", b"%PDF")
        from app.services import requirements as req_svc

        req_svc.delete_requirement(db, world["admin"], rid, confirm_task_count=0)
        rows = db.query(Attachment).all()
        assert all(a.deleted_at is not None for a in rows)

    def test_download_soft_deleted_not_found(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        a = svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "gone.txt", b"x")
        svc.soft_delete(db, world["admin"], a.id)
        with pytest.raises(AppError) as e:
            svc.download(db, world["admin"], a.id)
        assert e.value.code == "not_found"

    def test_unsupported_target_type_rejected(self, db: Session, world: dict, isolated_storage):
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "milestone", uuid.uuid4(), "a.txt", b"x")
        assert e.value.code == "invalid_request"
        assert "不支持的目标类型" in e.value.message

    def test_empty_file_name_rejected(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "   ", b"x")
        assert e.value.code == "invalid_request"

    def test_upload_missing_target_not_found(self, db: Session, world: dict, isolated_storage):
        with pytest.raises(AppError) as e:
            svc.upload(db, world["agent"], world["project"].id, "requirement", "REQ-999", "a.txt", b"x")
        assert e.value.code == "not_found"

    def test_download_missing_file_not_found(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        a = svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "lost.bin", b"x")
        svc._attachment_path(a.project_id, a.id).unlink()
        with pytest.raises(AppError) as e:
            svc.download(db, world["member"], a.id)
        assert e.value.code == "not_found"

    def test_soft_delete_missing_not_found(self, db: Session, world: dict, isolated_storage):
        with pytest.raises(AppError) as e:
            svc.soft_delete(db, world["admin"], uuid.uuid4())
        assert e.value.code == "not_found"

    def test_restore_only_for_deleted(self, db: Session, world: dict, isolated_storage):
        r = make_requirement(db, world)
        a = svc.upload(db, world["agent"], world["project"].id, "requirement", r["id"], "keep.txt", b"x")
        with pytest.raises(AppError) as e:
            svc.restore(db, world["admin"], a.id)
        assert e.value.code == "not_found"
        with pytest.raises(AppError) as e:
            svc.restore(db, world["admin"], uuid.uuid4())
        assert e.value.code == "not_found"


class TestAttachmentApi:
    def test_upload_download_api(self, db: Session, world: dict, isolated_storage, client):
        from app.tests.conftest import login

        login(client, "admin", "admin-pass-1")
        r = make_requirement(db, world)
        rid = r["id"]
        resp = client.post(
            f"/api/targets/requirement/{rid}/attachments",
            files={"file": ("readme.txt", b"api upload", "text/plain")},
        )
        assert resp.status_code == 201, resp.text
        aid = resp.json()["id"]
        # 列表
        listing = client.get(f"/api/targets/requirement/{rid}/attachments")
        assert len(listing.json()["items"]) == 1
        # 下载
        dl = client.get(f"/api/attachments/{aid}/download")
        assert dl.status_code == 200
        assert dl.content == b"api upload"
        # 删除
        assert client.delete(f"/api/attachments/{aid}").status_code == 200
        assert len(client.get(f"/api/targets/requirement/{rid}/attachments").json()["items"]) == 0


class TestAttachmentMcpPayload:
    """MCP attachment.upload 的 data 参数是 base64 字符串(不是 bytes)。

    回归:FastMCP 的 bytes 参数 schema 标记为 format=binary,但 pydantic 不会
    自动 base64 解码,data 会原样成为 UTF-8 字节。MCP 层必须显式 b64decode。
    """

    def test_base64_roundtrip_through_service(self, db: Session, world: dict, isolated_storage):
        import base64

        r = make_requirement(db, world)
        rid = r["id"]
        raw = b"\x89PNG\r\n\x1a\n fake-image-bytes " * 20

        # 模拟 MCP 层行为:data 是 base64 字符串,解码后传给 service
        payload = base64.b64encode(raw).decode()
        decoded = base64.b64decode(payload, validate=True)
        assert decoded == raw

        a = svc.upload(db, world["agent"], world["project"].id, "requirement", rid, "logo.png", decoded)
        _, data, _ = svc.download(db, world["member"], a.id)
        assert data == raw
        assert a.size == len(raw) == 520

    def test_invalid_base64_rejected(self):
        import base64

        with pytest.raises(Exception):
            base64.b64decode("!!!not-base64!!!", validate=True)
