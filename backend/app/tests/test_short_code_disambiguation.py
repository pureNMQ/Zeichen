"""REQ-55 短码跨项目撞名消歧:全局短码接口接受可选 project_id 在指定项目内解析。

跨项目同码在 ADR 0002 下合法;无项目上下文解析多命中 → invalid_request(既有语义,
本文件同时补齐该分支的缺失覆盖);携带 project_id 时严格项目内解析:
未命中 → not_found,无项目访问权 → not_found(不泄露存在性)。
覆盖三层:resolve_by_code 服务、REST 全局端点、MCP 工具面。
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.errors import AppError
from app.services import documents as document_svc
from app.services import requirements as req_svc
from app.services import short_code_lookup
from app.services import tasks as task_svc
from app.tests.conftest import login

BACKEND_DIR = Path(__file__).resolve().parents[2]


# ---------- 服务层:resolve_by_code ----------


@pytest.fixture()
def collision(db: Session, world: dict) -> dict:
    """两个项目各建 REQ-1/TASK-1/DOC-1,制造跨项目同码。"""
    from app.models import Project

    p1 = world["project"]
    p2 = Project(team_id=world["team"].id, name="second")
    db.add(p2)
    db.commit()
    admin = world["admin"]
    built = {"p1": p1, "p2": p2}
    for project in (p1, p2):
        r = req_svc.create_requirement(db, admin, project.id, "需求")
        r.status = "backlog"  # 直改 ORM:全局 set_status 会撞多命中(即本缺陷)
        t = task_svc.create_task(db, admin, project.id, "任务", requirement_id=r.code)
        d, _ = document_svc.create_document(db, admin, project.id, "文档", "wiki", "", None, None, None)
        built.setdefault("req", r.code)
        built.setdefault("task", t.code)
        built.setdefault("doc", d.code)
        built[str(project.id)] = project
    built.update(world)
    return built


class TestResolveByCode:
    def test_multi_hit_raises_invalid_request(self, db: Session, world: dict, collision: dict):
        with pytest.raises(AppError) as e:
            short_code_lookup.resolve_by_code(db, world["admin"], "task", collision["task"])
        assert e.value.code == "invalid_request"
        assert "多个项目" in e.value.message

    def test_scoped_resolves_within_project(self, db: Session, world: dict, collision: dict):
        entity, project = short_code_lookup.resolve_by_code(
            db, world["admin"], "task", collision["task"], project_id=collision["p2"].id
        )
        assert project.id == collision["p2"].id

    def test_scoped_unknown_code_not_found(self, db: Session, world: dict, collision: dict):
        with pytest.raises(AppError) as e:
            short_code_lookup.resolve_by_code(
                db, world["admin"], "task", "TASK-999", project_id=collision["p1"].id
            )
        assert e.value.code == "not_found"

    def test_scoped_without_project_access_not_found(self, db: Session, world: dict, collision: dict):
        # bob 仅 demo(p1) viewer,对 p2 无任何角色 → 不泄露存在性
        with pytest.raises(AppError) as e:
            short_code_lookup.resolve_by_code(
                db, world["member"], "task", collision["task"], project_id=collision["p2"].id
            )
        assert e.value.code == "not_found"


# ---------- REST:全局短码端点接受 project_id ----------


@pytest.fixture()
def logged_in(client: TestClient, collision: dict) -> dict:
    login(client, "admin", "admin-pass-1")
    return collision


class TestRestDisambiguation:
    def test_task_status_without_project_rejected(self, client: TestClient, logged_in: dict):
        resp = client.post(f"/api/tasks/{logged_in['task']}/status", json={"status": "in_progress"})
        assert resp.status_code == 400
        assert "多个项目" in resp.json()["message"]

    def test_task_status_with_project_disambiguates(self, client: TestClient, logged_in: dict):
        resp = client.post(
            f"/api/tasks/{logged_in['task']}/status",
            json={"status": "in_progress"},
            params={"project_id": str(logged_in["p2"].id)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "in_progress"
        # 另一项目同码任务不受影响
        other = client.get(
            f"/api/tasks/{logged_in['task']}",
            params={"project_id": str(logged_in["p1"].id)},
        )
        assert other.status_code == 200
        assert other.json()["status"] == "backlog"

    def test_task_get_scoped(self, client: TestClient, logged_in: dict):
        ok = client.get(
            f"/api/tasks/{logged_in['task']}",
            params={"project_id": str(logged_in["p1"].id)},
        )
        assert ok.status_code == 200
        assert ok.json()["project_id"] == str(logged_in["p1"].id)
        without = client.get(f"/api/tasks/{logged_in['task']}")
        assert without.status_code == 400

    def test_task_assign_scoped(self, client: TestClient, logged_in: dict):
        resp = client.post(
            f"/api/tasks/{logged_in['task']}/assign",
            json={"assignee_id": str(logged_in["admin"].id)},
            params={"project_id": str(logged_in["p2"].id)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["assignee_username"] == "admin"

    def test_requirement_update_scoped(self, client: TestClient, logged_in: dict):
        resp = client.patch(
            f"/api/requirements/{logged_in['req']}",
            json={"title": "改名"},
            params={"project_id": str(logged_in["p2"].id)},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "改名"

    def test_document_get_scoped(self, client: TestClient, logged_in: dict):
        ok = client.get(
            f"/api/documents/wiki/{logged_in['doc']}",
            params={"project_id": str(logged_in["p2"].id)},
        )
        assert ok.status_code == 200
        assert ok.json()["project_id"] == str(logged_in["p2"].id)
        without = client.get(f"/api/documents/wiki/{logged_in['doc']}")
        assert without.status_code == 400

    def test_comment_create_scoped(self, client: TestClient, logged_in: dict):
        ok = client.post(
            f"/api/targets/requirement/{logged_in['req']}/comments",
            json={"body": "评论"},
            params={"project_id": str(logged_in["p1"].id)},
        )
        assert ok.status_code == 201, ok.text
        without = client.post(
            f"/api/targets/requirement/{logged_in['req']}/comments", json={"body": "评论"}
        )
        assert without.status_code == 400

    def test_watch_scoped(self, client: TestClient, logged_in: dict):
        ok = client.post(
            f"/api/targets/task/{logged_in['task']}/watch",
            params={"project_id": str(logged_in["p1"].id)},
        )
        assert ok.status_code == 201, ok.text

    def test_task_restore_scoped(self, client: TestClient, logged_in: dict):
        deleted = client.post(
            f"/api/tasks/{logged_in['task']}/delete",
            params={"project_id": str(logged_in["p2"].id)},
        )
        assert deleted.status_code == 200, deleted.text
        restored = client.post(
            f"/api/tasks/{logged_in['task']}/restore",
            params={"project_id": str(logged_in["p2"].id)},
        )
        assert restored.status_code == 200, restored.text

    def test_scoped_unknown_code_404(self, client: TestClient, logged_in: dict):
        resp = client.get(
            "/api/tasks/TASK-999",
            params={"project_id": str(logged_in["p1"].id)},
        )
        assert resp.status_code == 404

    def test_single_project_unchanged(self, client: TestClient, db: Session, world: dict):
        """单项目用户体验不变:无 project_id 时全局解析照常命中。"""
        login(client, "admin", "admin-pass-1")
        r = req_svc.create_requirement(db, world["admin"], world["project"].id, "solo")
        resp = client.get(f"/api/requirements/{r.code}")
        assert resp.status_code == 200
        assert resp.json()["id"] == r.code


# ---------- MCP:工具面 project_id 消歧 ----------


@pytest.fixture(scope="module")
def mcp_two_projects(tmp_path_factory):
    """双项目 e2e 环境:agent 附属 admin,同码实体经 MCP 自建。"""
    import os

    db_file = tmp_path_factory.mktemp("mcp") / "disambig.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    from sqlalchemy import create_engine

    from app.models import ApiKey, Base, Project, Team, User, WorkspaceMember
    from app.security import generate_api_token, hash_password, token_digest

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        team = Team(name="贼船")
        db.add(team)
        db.flush()
        admin = User(username="admin", password_hash=hash_password("admin-pass-1"), is_agent=False)
        db.add(admin)
        db.flush()
        db.add(WorkspaceMember(team_id=team.id, user_id=admin.id, role="admin"))
        agent = User(username="agent-dis", password_hash="", is_agent=True, owner_id=admin.id)
        db.add(agent)
        db.flush()
        pa = Project(team_id=team.id, name="PA")
        pb = Project(team_id=team.id, name="PB")
        db.add_all([pa, pb])
        db.flush()
        token = generate_api_token()
        db.add(ApiKey(user_id=agent.id, token_hash=token_digest(token), note="dis"))
        db.commit()
        ids = {"pa": str(pa.id), "pb": str(pb.id), "token": token}
    engine.dispose()

    from app.tests.test_mcp_e2e import RawMcpClient, _free_port

    port = _free_port()
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["SESSION_SECRET"] = "test-session-secret-0123456789abcdef"
    log_file = db_file.parent / "server.log"
    with log_file.open("w") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.mcp_server.main:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
            cwd=BACKEND_DIR, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}/mcp"
    deadline = time.time() + 20
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"MCP server 提前退出: {proc.returncode}\n{log_file.read_text()}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                ready = True
                break
        except OSError:
            time.sleep(0.2)
    assert ready, "MCP server 未就绪"

    client = RawMcpClient(url, ids["token"])
    client.initialize()
    try:
        yield {"client": client, **ids}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def same_codes(mcp_two_projects: dict) -> dict:
    """在两个项目各建 REQ-1 + TASK-1,返回同码与项目 id。"""
    mcp = mcp_two_projects["client"]
    codes = {}
    for key in ("pa", "pb"):
        pid = mcp_two_projects[key]
        r = mcp.call("requirements.create", project_id=pid, title="需求")
        assert "error" not in r, r
        # 第二个 REQ-1 出现后全局解析已多命中:夹具即经被测消歧通道置状态
        s = mcp.call(
            "requirements.set_status", id=r["id"], status="backlog", project_id=pid
        )
        assert "error" not in s, s
        t = mcp.call("tasks.create", project_id=pid, title="任务", requirement_id=r["id"])
        assert "error" not in t, t
        codes.setdefault("req", r["id"])
        codes.setdefault("task", t["id"])
    return codes


class TestMcpDisambiguation:
    def test_get_without_project_rejected(self, mcp_two_projects: dict, same_codes: dict):
        got = mcp_two_projects["client"].call("tasks.get", id=same_codes["task"])
        # schema 级必传校验:缺 project_id 直接被参数校验拒绝
        assert "error" in got and "project_id" in got["error"], got

    def test_single_hit_without_project_also_rejected(self, mcp_two_projects: dict):
        """接口统一(REQ-55 返工):缺省 project_id 的短码寻址一律拒绝,单命中也不例外。"""
        mcp = mcp_two_projects["client"]
        pid = mcp_two_projects["pa"]
        r = mcp.call("requirements.create", project_id=pid, title="仅PA需求")
        assert "error" not in r, r
        got = mcp.call("requirements.get", id=r["id"])
        assert "error" in got and "project_id" in got["error"], got
        # 携带 project_id 正常寻址
        ok = mcp.call("requirements.get", id=r["id"], project_id=pid)
        assert "error" not in ok, ok

    def test_comment_entity_target_requires_project(self, mcp_two_projects: dict, same_codes: dict):
        """多态工具:实体短码目标必传 project_id;project 目标(UUID 寻址)可省。"""
        mcp = mcp_two_projects["client"]
        missing = mcp.call(
            "comment.create", target_type="requirement", target_id=same_codes["req"], body="x"
        )
        assert "error" in missing and "invalid_request" in missing["error"], missing
        assert "project_id" in missing["error"], missing
        ok = mcp.call(
            "comment.create", target_type="requirement", target_id=same_codes["req"],
            body="x", project_id=mcp_two_projects["pa"],
        )
        assert "error" not in ok, ok
        # project 目标无需 project_id
        proj = mcp.call(
            "comment.create", target_type="project", target_id=mcp_two_projects["pa"], body="y"
        )
        assert "error" not in proj, proj

    def test_get_with_project_disambiguates(self, mcp_two_projects: dict, same_codes: dict):
        got = mcp_two_projects["client"].call(
            "tasks.get", id=same_codes["task"], project_id=mcp_two_projects["pb"]
        )
        assert "error" not in got, got
        assert got["project_id"] == mcp_two_projects["pb"]

    def test_set_status_scoped_only_touches_target_project(
        self, mcp_two_projects: dict, same_codes: dict
    ):
        mcp = mcp_two_projects["client"]
        done = mcp.call(
            "tasks.set_status", id=same_codes["task"], status="in_progress",
            project_id=mcp_two_projects["pa"],
        )
        assert "error" not in done, done
        other = mcp.call(
            "tasks.get", id=same_codes["task"], project_id=mcp_two_projects["pb"]
        )
        assert other["status"] == "backlog"

    def test_requirement_update_scoped(self, mcp_two_projects: dict, same_codes: dict):
        mcp = mcp_two_projects["client"]
        updated = mcp.call(
            "requirements.update", id=same_codes["req"], title="改名",
            project_id=mcp_two_projects["pb"],
        )
        assert "error" not in updated, updated
        assert updated["title"] == "改名"
        untouched = mcp.call(
            "requirements.get", id=same_codes["req"], project_id=mcp_two_projects["pa"]
        )
        assert untouched["title"] == "需求"
