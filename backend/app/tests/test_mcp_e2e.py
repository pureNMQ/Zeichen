"""MCP 端到端验证(规格书 §4):真实 uvicorn 服务 + Bearer API key + 工具全链路。

客户端为最小 wire 协议实现(mcp SDK 1.28/1.29 自带 client 传输在本环境有
transport bug,§9 记录):POST initialize → Mcp-Session-Id → POST tools/call,
响应经 SSE 事件随 POST body 返回。

核心链路(ticket 09):agent 认领 → set_status 自由流转(实现中→验收中→已完成)
→ **显式** requirements.set_status 置需求已完成(自动流转已删除,需求状态全手动);
错误四件套经 MCP 错误消息 `code: message` 透出。
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _parse_sse(body: str) -> list[dict]:
    msgs = []
    for block in body.split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data:")]
        if data:
            msgs.append(json.loads("\n".join(data)))
    return msgs


class RawMcpClient:
    """最小 MCP streamable-http 客户端(仅覆盖本测试所需)。"""

    def __init__(self, url: str, token: str | None = None):
        self.url = url
        self.session_id: str | None = None
        self._id = 0
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    def initialize(self) -> dict:
        result = self._post(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "zeichen-e2e", "version": "0"}},
            is_initialize=True,
        )
        return result

    def list_tools(self) -> list[str]:
        result = self._post("tools/list", {})
        return [t["name"] for t in result["tools"]]

    def call(self, tool_name: str, **arguments) -> dict:
        result = self._post("tools/call", {"name": tool_name, "arguments": arguments})
        if "error" in result:
            return result
        if result.get("isError"):
            texts = [c.get("text", "") for c in result.get("content", [])]
            return {"error": " ".join(texts).strip()}
        if "structuredContent" in result and isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"].get("result", result["structuredContent"])
        texts = [c["text"] for c in result["content"] if c.get("type") == "text"]
        if len(texts) == 1:
            return json.loads(texts[0])
        return [json.loads(t) for t in texts]

    def _post(self, method: str, params: dict, is_initialize: bool = False) -> dict:
        headers = dict(self._headers)
        if not is_initialize:
            if self.session_id is None:
                raise RuntimeError("未先 initialize")
            headers["Mcp-Session-Id"] = self.session_id
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        # 本地 uvicorn 回环请求不应继承机器代理设置；否则部分环境会把
        # 127.0.0.1 的 MCP 初始化转发并返回空的 502。
        with httpx.Client(timeout=30, trust_env=False) as client:
            resp = client.post(self.url, headers=headers, json=payload)
            resp.raise_for_status()
            if is_initialize:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            msgs = _parse_sse(resp.text)
        if not msgs:
            raise RuntimeError(f"无 SSE 响应: {method} {resp.status_code}")
        msg = msgs[0]
        if "error" in msg:
            return {"error": msg["error"]["message"]}
        return msg["result"]


@pytest.fixture(scope="module")
def mcp_server(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("mcp") / "e2e.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import ApiKey, Base, Project, ProjectMember, Team, User, WorkspaceMember
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
        agent = User(username="agent-e2e", password_hash="", is_agent=True)
        db.add(agent)
        db.flush()
        project = Project(team_id=team.id, name="E2E")
        db.add(project)
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=agent.id, role="editor"))
        token = generate_api_token()
        db.add(ApiKey(user_id=agent.id, token_hash=token_digest(token), token_encrypted="x", note="e2e"))
        db.commit()
        ids = {"project_id": str(project.id), "agent_id": str(agent.id), "token": token}
    engine.dispose()

    port = _free_port()
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["SESSION_SECRET"] = "test-session-secret-0123456789abcdef"
    log_file = db_file.parent / "server.log"
    with log_file.open("w") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.mcp_server.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=BACKEND_DIR,
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
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
    try:
        yield {**ids, "url": url, "log_file": log_file}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_agent_claim_to_requirement_done(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    init = client.initialize()
    assert init["serverInfo"]["name"] == "zeichen"
    assert client.session_id is not None

    tools = client.list_tools()
    assert len(tools) >= 70
    for ns in ("requirements.", "tasks.", "docs.wiki.", "docs.glossary.", "docs.api.", "comment.", "ref.", "project.", "agent."):
        assert any(t.startswith(ns) for t in tools), f"缺少 {ns} 工具"
    assert "requirements.set_status" in tools and "requirements.complete" not in tools
    assert "tasks.set_status" in tools and "tasks.start" not in tools and "tasks.complete" not in tools
    for name in (
        "docs.wiki.children", "docs.wiki.ancestors", "docs.wiki.move",
        "docs.glossary.directory_create", "docs.glossary.directory_move",
        "docs.api.directory_create", "docs.api.children",
    ):
        assert name in tools

    me = client.call("agent.whoami")
    assert me["username"] == "agent-e2e"
    assert me["is_agent"] is True
    assert me["project_grants"][0]["role"] == "editor"

    projects = client.call("project.list")
    assert projects[0]["id"] == mcp_server["project_id"], f"project.list 返回异常: {projects}"

    req = client.call("requirements.create", project_id=mcp_server["project_id"], title="E2E 需求")
    rid = req["id"]
    assert req["status"] == "backlog"

    task = client.call(
        "tasks.create", project_id=mcp_server["project_id"], title="E2E 任务", requirement_id=rid
    )
    tid = task["id"]

    # agent 认领 → set_status 自由流转:实现中 → 验收中
    claimed = client.call("tasks.claim", id=tid)
    assert claimed["assignee_id"] == mcp_server["agent_id"]
    assert client.call("tasks.set_status", id=tid, status="in_progress")["status"] == "in_progress"
    assert client.call("tasks.set_status", id=tid, status="verifying")["status"] == "verifying"

    # 需求带未决任务可直接置 done:无任何前置校验(方案 B 完全自由)
    assert client.call("requirements.set_status", id=rid, status="done")["status"] == "done"
    # 完全自由流转双向:需求可改回待办
    assert client.call("requirements.set_status", id=rid, status="backlog")["status"] == "backlog"

    # 任务完成后需求状态不变(自动流转已删除):需求仍待办,需显式 set_status
    assert client.call("tasks.set_status", id=tid, status="done")["status"] == "done"
    assert client.call("requirements.get", id=rid)["status"] == "backlog"
    assert client.call("requirements.set_status", id=rid, status="done")["status"] == "done"

    # 终态再转 → conflict;非法状态 → invalid_request
    err2 = client.call("tasks.set_status", id=tid, status="done")
    assert "conflict" in err2["error"]
    err3 = client.call("tasks.set_status", id=tid, status="nonsense")
    assert "invalid_request" in err3["error"]

    # 完全自由流转双向:已指派者本人可把任务从终态改回待办
    assert client.call("tasks.set_status", id=tid, status="backlog")["status"] == "backlog"
    assert client.call("tasks.set_status", id=tid, status="done")["status"] == "done"

    # 取消便捷封装 → cancelled,再取消 → conflict
    assert client.call("requirements.cancel", id=rid)["status"] == "cancelled"
    err5 = client.call("requirements.cancel", id=rid)
    assert "conflict" in err5["error"]

    # 评论 + 双向引用 + 活动
    client.call("comment.create", target_type="requirement", target_id=rid, body="e2e 评论")
    comments = client.call("comment.list", target_type="requirement", target_id=rid)
    assert len(comments["items"]) == 1
    ref = client.call(
        "ref.create", from_type="requirement", from_id=rid, to_type="task", to_id=tid, type="implements"
    )
    assert ref["type"] == "implements"
    assert len(client.call("ref.list", target_type="task", target_id=tid)["items"]) == 1

    # 需求软删二次确认
    assert "conflict" in client.call("requirements.delete", id=rid)["error"]
    assert client.call("requirements.delete", id=rid, confirm_task_count=1)["deleted"] is True
    assert client.call("requirements.restore", id=rid)["status"] == "cancelled"


def test_task_requirement_link_over_mcp(mcp_server: dict):
    """tasks.update 经 MCP 同步支持 requirement_id(设置/更换/解除)。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()

    r1 = client.call("requirements.create", project_id=mcp_server["project_id"], title="MCP 需求一")
    r2 = client.call("requirements.create", project_id=mcp_server["project_id"], title="MCP 需求二")
    t = client.call("tasks.create", project_id=mcp_server["project_id"], title="MCP 独立任务")
    assert t["requirement_id"] is None

    updated = client.call("tasks.update", id=t["id"], requirement_id=r1["id"])
    assert updated["requirement_id"] == r1["id"]
    changed = client.call("tasks.update", id=t["id"], requirement_id=r2["id"])
    assert changed["requirement_id"] == r2["id"]
    cleared = client.call("tasks.update", id=t["id"], requirement_id="")
    assert cleared["requirement_id"] is None

    # 关联后 tasks.list 可按 requirement_id 过滤
    client.call("tasks.update", id=t["id"], requirement_id=r1["id"])
    page = client.call("tasks.list", project_id=mcp_server["project_id"], requirement_id=r1["id"])
    assert [i["id"] for i in page["items"]] == [t["id"]]

    # 清理本测试建的需求(恢复 pagination 基线)
    assert client.call("requirements.delete", id=r1["id"], confirm_task_count=1)["deleted"] is True
    assert client.call("requirements.delete", id=r2["id"])["deleted"] is True


def test_document_hierarchy_over_mcp(mcp_server: dict):
    """MCP 与 HTTP 共用层级/目录 service，而不是第二套规则。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    project_id = mcp_server["project_id"]
    root = client.call("docs.wiki.create", project_id=project_id, title="MCP 根")
    child = client.call("docs.wiki.create", project_id=project_id, title="MCP 子", parent_id=root["id"])
    children = client.call("docs.wiki.children", project_id=project_id, parent_id=root["id"])
    assert [node["id"] for node in children["items"]] == [child["id"]]
    path = client.call("docs.wiki.ancestors", project_id=project_id, id=child["id"])
    assert [node["id"] for node in path["items"]] == [root["id"], child["id"]]
    assert "invalid_request" in client.call("docs.wiki.move", id=root["id"], parent_id=child["id"])["error"]

    directory = client.call("docs.api.directory_create", project_id=project_id, name="MCP 服务")
    definition = client.call(
        "docs.api.create",
        project_id=project_id,
        title="MCP 接口",
        directory_id=directory["id"],
        metadata={"endpoint": {"method": "GET", "path": "/mcp"}, "schema": {"fields": []}},
    )
    api_children = client.call("docs.api.children", project_id=project_id, parent_id=directory["id"])
    assert [node["id"] for node in api_children["items"]] == [definition["id"]]


def test_cursor_pagination_over_mcp(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    for i in range(25):
        client.call("requirements.create", project_id=mcp_server["project_id"], title=f"批量 {i}")
    page1 = client.call("requirements.list", project_id=mcp_server["project_id"], status="backlog", limit=10)
    assert len(page1["items"]) == 10
    assert page1["next_cursor"] is not None
    page2 = client.call(
        "requirements.list", project_id=mcp_server["project_id"], status="backlog", limit=10, cursor=page1["next_cursor"]
    )
    assert len(page2["items"]) == 10
    page3 = client.call(
        "requirements.list", project_id=mcp_server["project_id"], status="backlog", limit=10, cursor=page2["next_cursor"]
    )
    assert len(page3["items"]) == 5
    assert page3["next_cursor"] is None
    # 跨条件游标 → invalid_request
    err = client.call(
        "requirements.list", project_id=mcp_server["project_id"], status="done", cursor=page1["next_cursor"]
    )
    assert "invalid_request" in err["error"]


def test_bad_key_rejected(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], "zc_invalid-key-0000000000")
    with pytest.raises(httpx.HTTPStatusError) as e:
        client.initialize()
    assert e.value.response.status_code == 401
