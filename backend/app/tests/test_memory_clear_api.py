"""REQ-4 记忆清空 API 红灯测试(需求 515adbd2 要点 1)。

契约:
- DELETE /api/projects/{project_id}/memory?confirmed=true
- 仅人类用户且具备项目写权限(editor+):agent → 403,viewer → 403
- 缺失/未确认 confirmed → 400 invalid_request(语义失败,不得 500)
- 成功写 activity(action=memory_clear);清空范围=当前项目,不跨项目
服务层 clear() 已存在;路由未实现前用例全部红灯(404)。
"""

import pytest  # noqa: F401
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Activity, MemoryDataset, Project
from app.security import SESSION, create_token
from app.services import memory as memory_service
from app.tests.conftest import login


class ScopedFakeCognee:
    """按 dataset 记录会话,用于验证清空范围不跨项目。"""

    def __init__(self):
        self.calls = []
        self.sessions: dict[str, list[str]] = {}

    def list_sessions(self, dataset_id):
        self.calls.append(("list_sessions", dataset_id))
        return [{"id": sid} for sid in self.sessions.get(dataset_id, [])]

    def delete_session(self, session_id):
        self.calls.append(("delete_session", session_id))

    def delete_dataset(self, dataset_id):
        self.calls.append(("delete_dataset", dataset_id))


def _seed_other_project_with_datasets(db: Session, world: dict) -> Project:
    """第二项目 + 两项目各自的 MemoryDataset,验证清空不跨项目。"""
    other = Project(team_id=world["team"].id, name="other")
    db.add(other)
    db.commit()
    db.add(MemoryDataset(project_id=world["project"].id, cognee_dataset_id="ds-demo"))
    db.add(MemoryDataset(project_id=other.id, cognee_dataset_id="ds-other"))
    db.commit()
    return other


def _seed_sessions(world: dict, other: Project, fake: ScopedFakeCognee) -> None:
    pid = str(world["project"].id)
    agent_id = str(world["agent"].id)
    fake.sessions["ds-demo"] = [f"zeichen:{pid}:{agent_id}:s1", "foreign:unrelated"]
    fake.sessions["ds-other"] = [f"zeichen:{other.id}:{agent_id}:s2"]


def _session_cookie(client: TestClient, user) -> None:
    """为无密码用户(agent/viewer)直接铸造会话 cookie。"""
    client.cookies.set(get_settings().session_cookie_name, create_token(str(user.id), SESSION))


def test_clear_requires_confirmed(client, db, world, monkeypatch):
    fake = ScopedFakeCognee()
    monkeypatch.setattr(memory_service, "CogneeClient", lambda: fake)
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)

    missing = client.delete(f"/api/projects/{pid}/memory")
    unconfirmed = client.delete(f"/api/projects/{pid}/memory?confirmed=false")

    assert missing.status_code == 400, missing.text
    assert missing.json()["code"] == "invalid_request"
    assert unconfirmed.status_code == 400, unconfirmed.text
    assert unconfirmed.json()["code"] == "invalid_request"
    assert not [name for name, _ in fake.calls if name == "delete_dataset"]


def test_clear_rejects_agent_identity(client, db, world, monkeypatch):
    fake = ScopedFakeCognee()
    monkeypatch.setattr(memory_service, "CogneeClient", lambda: fake)
    _session_cookie(client, world["agent"])

    resp = client.delete(f"/api/projects/{world['project'].id}/memory?confirmed=true")

    assert resp.status_code == 403, resp.text
    body = resp.json()
    assert body["code"] == "permission_denied"
    assert "人类" in body["message"]
    assert fake.calls == []


def test_clear_rejects_human_without_project_write(client, db, world, monkeypatch):
    fake = ScopedFakeCognee()
    monkeypatch.setattr(memory_service, "CogneeClient", lambda: fake)
    _session_cookie(client, world["member"])  # viewer:项目内只读

    resp = client.delete(f"/api/projects/{world['project'].id}/memory?confirmed=true")

    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "permission_denied"
    assert fake.calls == []


def test_clear_success_is_scoped_to_project_and_records_activity(client, db, world, monkeypatch):
    fake = ScopedFakeCognee()
    monkeypatch.setattr(memory_service, "CogneeClient", lambda: fake)
    other = _seed_other_project_with_datasets(db, world)
    _seed_sessions(world, other, fake)
    login(client, "admin", "admin-pass-1")
    pid = str(world["project"].id)

    resp = client.delete(f"/api/projects/{pid}/memory?confirmed=true")

    assert resp.status_code == 200, resp.text
    deleted_datasets = [arg for name, arg in fake.calls if name == "delete_dataset"]
    assert deleted_datasets == ["ds-demo"]
    deleted_sessions = [arg for name, arg in fake.calls if name == "delete_session"]
    assert f"zeichen:{pid}:{world['agent'].id}:s1" in deleted_sessions
    assert "foreign:unrelated" not in deleted_sessions
    assert f"zeichen:{other.id}:{world['agent'].id}:s2" not in deleted_sessions
    assert db.query(Activity).filter(Activity.action == "memory_clear").count() == 1
    remaining = db.query(MemoryDataset).filter(MemoryDataset.project_id == other.id).count()
    assert remaining == 1
    cleared = db.query(MemoryDataset).filter(MemoryDataset.project_id == world["project"].id).count()
    assert cleared == 0


def test_clear_requires_login(client, world):
    resp = client.delete(f"/api/projects/{world['project'].id}/memory?confirmed=true")
    assert resp.status_code == 401
