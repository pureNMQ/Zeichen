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

    def __init__(
        self,
        url: str,
        token: str | None = None,
        origin: str | None = None,
        host: str | None = None,
    ):
        self.url = url
        self.session_id: str | None = None
        self._initialized = False
        self._id = 0
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        if origin:
            self._headers["Origin"] = origin
        if host:
            self._headers["Host"] = host

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
            if not self._initialized:
                raise RuntimeError("未先 initialize")
            # stateless 模式服务端不签发会话 id:仅在持有会话 id 时附带。
            if self.session_id:
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
                self._initialized = True
            msgs = _parse_sse(resp.text)
        if not msgs:
            raise RuntimeError(f"无 SSE 响应: {method} {resp.status_code}")
        msg = msgs[0]
        if "error" in msg:
            return {"error": msg["error"]["message"]}
        return msg["result"]


@pytest.fixture(scope="module")
def mcp_server(tmp_path_factory, request):
    db_file = tmp_path_factory.mktemp("mcp") / "e2e.db"
    db_url = f"sqlite:///{db_file.as_posix()}"

    from sqlalchemy import create_engine, select
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
        # ADR 0004:agent 附属 admin,继承其全项目 owner 级访问
        agent = User(username="agent-e2e", password_hash="", is_agent=True, owner_id=admin.id)
        db.add(agent)
        db.flush()
        project = Project(team_id=team.id, name="E2E")
        db.add(project)
        db.flush()
        token = generate_api_token()
        db.add(ApiKey(user_id=agent.id, token_hash=token_digest(token), note="e2e"))
        db.commit()
        ids = {"project_id": str(project.id), "agent_id": str(agent.id), "token": token}
    engine.dispose()

    port = _free_port()
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["SESSION_SECRET"] = "test-session-secret-0123456789abcdef"
    env.update(getattr(request, "param", {}))
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
    assert client.session_id is None, "stateless 模式不签发 Mcp-Session-Id"

    tools = client.list_tools()
    assert len(tools) >= 40  # 当前注册 54 个;REQ-59 移除 docs.glossary.* 后同步放宽下限
    for ns in ("requirements.", "tasks.", "repositories.", "docs.wiki.", "comment.", "ref.", "project.", "agent."):
        assert any(t.startswith(ns) for t in tools), f"缺少 {ns} 工具"
    assert not any(t.startswith("docs.code.") for t in tools), "docs.code.* 工具应随 API 参考模块移除"
    assert "requirements.set_status" in tools and "requirements.complete" not in tools
    assert "tasks.set_status" in tools and "tasks.start" not in tools and "tasks.complete" not in tools
    assert not any(t.startswith("memory.") for t in tools), "REQ-57:记忆工具应随记忆系统下线移除"
    assert not any(t.startswith("docs.glossary.") for t in tools), "REQ-59:词条工具应随 glossary 合并 wiki 下线"
    for name in (
        "docs.wiki.children", "docs.wiki.ancestors", "docs.wiki.move", "docs.wiki.index", "docs.search",
        "repositories.list", "repositories.create", "repositories.update", "repositories.delete", "repositories.restore",
    ):
        assert name in tools

    me = client.call("agent.whoami")
    assert me["username"] == "agent-e2e"
    assert me["is_agent"] is True
    # ADR 0004:agent 附属 admin,继承全项目 owner 级;whoami 透出宿主
    assert me["owner"]["username"] == "admin"
    assert me["project_grants"][0]["role"] == "owner"

    projects = client.call("project.list")
    assert projects[0]["id"] == mcp_server["project_id"], f"project.list 返回异常: {projects}"

    repository = client.call(
        "repositories.create", project_id=mcp_server["project_id"], name="MCP Repository",
        vcs_type="git", url="https://example.com/mcp-repository.git", default_branch="main",
    )
    assert repository["vcs_type"] == "git"
    assert client.call("repositories.list", project_id=mcp_server["project_id"])["items"][0]["id"] == repository["id"]
    assert client.call("repositories.update", id=repository["id"], description="MCP registered")["description"] == "MCP registered"
    assert client.call("repositories.delete", id=repository["id"])["deleted"] is True
    assert client.call("repositories.deleted", project_id=mcp_server["project_id"])["items"][0]["id"] == repository["id"]
    assert client.call("repositories.restore", id=repository["id"])["deleted_at"] is None

    req = client.call("requirements.create", project_id=mcp_server["project_id"], title="E2E 需求")
    rid = req["id"]
    assert req["status"] == "pending"

    # 待确认需求不可派生任务;确认后进入正常执行流。
    blocked = client.call(
        "tasks.create", project_id=mcp_server["project_id"], title="过早拆解", requirement_id=rid
    )
    assert "invalid_request" in blocked["error"]
    assert client.call("requirements.set_status", id=rid, status="backlog", project_id=mcp_server["project_id"])["status"] == "backlog"

    task = client.call(
        "tasks.create", project_id=mcp_server["project_id"], title="E2E 任务", requirement_id=rid
    )
    tid = task["id"]

    # agent 认领 → set_status 自由流转(任务四态,verifying 已删 → invalid_request)
    claimed = client.call("tasks.claim", id=tid, project_id=mcp_server["project_id"])
    assert claimed["assignee_id"] == mcp_server["agent_id"]
    assert client.call("tasks.set_status", id=tid, status="in_progress", project_id=mcp_server["project_id"])["status"] == "in_progress"
    assert "invalid_request" in client.call("tasks.set_status", id=tid, status="verifying", project_id=mcp_server["project_id"])["error"]

    # 需求带未决任务可直接置 done:无任何前置校验(方案 B 完全自由)
    assert client.call("requirements.set_status", id=rid, status="done", project_id=mcp_server["project_id"])["status"] == "done"
    # 完全自由流转双向:需求可改回待办
    assert client.call("requirements.set_status", id=rid, status="backlog", project_id=mcp_server["project_id"])["status"] == "backlog"

    # 任务完成后需求状态不变(自动流转已删除):需求仍待办,需显式 set_status
    assert client.call("tasks.set_status", id=tid, status="done", project_id=mcp_server["project_id"])["status"] == "done"
    assert client.call("requirements.get", id=rid, project_id=mcp_server["project_id"])["status"] == "backlog"
    assert client.call("requirements.set_status", id=rid, status="done", project_id=mcp_server["project_id"])["status"] == "done"

    # 终态再转 → conflict;非法状态 → invalid_request
    err2 = client.call("tasks.set_status", id=tid, status="done", project_id=mcp_server["project_id"])
    assert "conflict" in err2["error"]
    err3 = client.call("tasks.set_status", id=tid, status="nonsense", project_id=mcp_server["project_id"])
    assert "invalid_request" in err3["error"]

    # 完全自由流转双向:已指派者本人可把任务从终态改回待办
    assert client.call("tasks.set_status", id=tid, status="backlog", project_id=mcp_server["project_id"])["status"] == "backlog"
    assert client.call("tasks.set_status", id=tid, status="done", project_id=mcp_server["project_id"])["status"] == "done"

    # 取消便捷封装 → cancelled,再取消 → conflict
    assert client.call("requirements.cancel", id=rid, project_id=mcp_server["project_id"])["status"] == "cancelled"
    err5 = client.call("requirements.cancel", id=rid, project_id=mcp_server["project_id"])
    assert "conflict" in err5["error"]

    # 评论 + 双向引用 + 活动
    client.call("comment.create", target_type="requirement", target_id=rid, body="e2e 评论", project_id=mcp_server["project_id"])
    comments = client.call("comment.list", target_type="requirement", target_id=rid, project_id=mcp_server["project_id"])
    assert len(comments["items"]) == 1
    ref = client.call(
        "ref.create", from_type="requirement", from_id=rid, to_type="task", to_id=tid,
        type="implements", project_id=mcp_server["project_id"],
    )
    assert ref["type"] == "implements"
    assert len(client.call("ref.list", target_type="task", target_id=tid, project_id=mcp_server["project_id"])["items"]) == 1

    # 需求软删二次确认
    assert "conflict" in client.call("requirements.delete", id=rid, project_id=mcp_server["project_id"])["error"]
    assert client.call("requirements.delete", id=rid, confirm_task_count=1, project_id=mcp_server["project_id"])["deleted"] is True
    assert client.call("requirements.restore", id=rid, project_id=mcp_server["project_id"])["status"] == "cancelled"


def test_task_requirement_link_over_mcp(mcp_server: dict):
    """tasks.create 必挂需求;tasks.update 只可改指向同项目其他需求,不可解除。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()

    r1 = client.call("requirements.create", project_id=mcp_server["project_id"], title="MCP 需求一")
    r2 = client.call("requirements.create", project_id=mcp_server["project_id"], title="MCP 需求二")
    client.call("requirements.set_status", id=r1["id"], status="backlog", project_id=mcp_server["project_id"])
    client.call("requirements.set_status", id=r2["id"], status="backlog", project_id=mcp_server["project_id"])

    # 缺 requirement_id → invalid_request
    orphan = client.call("tasks.create", project_id=mcp_server["project_id"], title="MCP 无主任务")
    assert "invalid_request" in orphan["error"]

    t = client.call(
        "tasks.create", project_id=mcp_server["project_id"], title="MCP 任务", requirement_id=r1["id"]
    )
    assert t["requirement_id"] == r1["id"]
    retitled = client.call("tasks.update", id=t["id"], title="MCP 已改标题", project_id=mcp_server["project_id"])
    assert retitled["title"] == "MCP 已改标题"
    assert retitled["requirement_id"] == r1["id"]
    changed = client.call("tasks.update", id=t["id"], requirement_id=r2["id"], project_id=mcp_server["project_id"])
    assert changed["requirement_id"] == r2["id"]

    # 置空/空字符串解除 → invalid_request(任务必须挂需求)
    for empty in (None, ""):
        cleared = client.call("tasks.update", id=t["id"], requirement_id=empty, project_id=mcp_server["project_id"])
        assert "invalid_request" in cleared["error"]

    # tasks.list 可按 requirement_id 过滤
    client.call("tasks.update", id=t["id"], requirement_id=r1["id"], project_id=mcp_server["project_id"])
    page = client.call("tasks.list", project_id=mcp_server["project_id"], requirement_id=r1["id"])
    assert [i["id"] for i in page["items"]] == [t["id"]]

    # 清理本测试建的需求(恢复 pagination 基线)
    assert client.call("requirements.delete", id=r1["id"], confirm_task_count=1, project_id=mcp_server["project_id"])["deleted"] is True
    assert client.call("requirements.delete", id=r2["id"], project_id=mcp_server["project_id"])["deleted"] is True


def test_document_hierarchy_over_mcp(mcp_server: dict):
    """MCP 与 HTTP 共用层级 service,而不是第二套规则;REQ-59 附带双链/INDEX/docs.search 冒烟。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    project_id = mcp_server["project_id"]
    root = client.call(
        "docs.wiki.create", project_id=project_id, title="MCP 根",
        content="---\ndoc_kind: concept\nsummary: 根页摘要\naliases: [根页别名]\n---\n根正文",
    )
    child = client.call(
        "docs.wiki.create", project_id=project_id, title="MCP 子",
        parent_id=root["id"], content=f"参见 [[MCP 根]] 与 [[悬空页]]",
    )
    assert child["reference_warning"]["count"] == 1  # 断链警告随保存返回
    assert child["metadata"].get("doc_kind") is None
    children = client.call("docs.wiki.children", project_id=project_id, parent_id=root["id"])
    assert [node["id"] for node in children["items"]] == [child["id"]]
    path = client.call("docs.wiki.ancestors", project_id=project_id, id=child["id"])
    assert [node["id"] for node in path["items"]] == [root["id"], child["id"]]
    assert "invalid_request" in client.call("docs.wiki.move", id=root["id"], project_id=project_id, parent_id=child["id"])["error"]

    detail = client.call("docs.wiki.get", id=root["id"], project_id=project_id)
    assert detail["metadata"]["doc_kind"] == "concept"
    assert [item["from_code"] for item in detail["links"]["incoming"]] == [child["id"]]  # 反链
    assert detail["author"]["is_agent"] is True and detail["author"]["owner"]["username"] == "admin"

    index = client.call("docs.wiki.index", project_id=project_id)
    assert index["total"] >= 2
    concept = next(section for section in index["sections"] if section["kind"] == "concept")
    assert any(item["id"] == root["id"] for item in concept["items"])
    assert index["lint"]["broken_links"] and index["lint"]["broken_links"][0]["raw_text"] == "悬空页"

    by_alias = client.call("docs.search", project_id=project_id, q="根页别名")
    assert any(item["id"] == root["id"] for item in by_alias["items"])
    by_multi = client.call("docs.search", project_id=project_id, q="根页 摘要")
    assert any(item["id"] == root["id"] for item in by_multi["items"])  # 多词 AND,别名+summary 参与
    in_body = client.call("docs.search", project_id=project_id, q="根正文")
    assert in_body["items"] and in_body["items"][0]["snippet"]  # 正文命中返回片段


def test_cursor_pagination_over_mcp(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    for i in range(25):
        client.call("requirements.create", project_id=mcp_server["project_id"], title=f"批量 {i}")
    page1 = client.call("requirements.list", project_id=mcp_server["project_id"], status="pending", limit=10)
    assert len(page1["items"]) == 10
    assert page1["next_cursor"] is not None
    page2 = client.call(
        "requirements.list", project_id=mcp_server["project_id"], status="pending", limit=10, cursor=page1["next_cursor"]
    )
    assert len(page2["items"]) == 10
    page3 = client.call(
        "requirements.list", project_id=mcp_server["project_id"], status="pending", limit=10, cursor=page2["next_cursor"]
    )
    assert len(page3["items"]) == 5
    assert page3["next_cursor"] is None
    # 跨条件游标 → invalid_request
    err = client.call(
        "requirements.list", project_id=mcp_server["project_id"], status="done", cursor=page1["next_cursor"]
    )
    assert "invalid_request" in err["error"]


def test_list_filters_over_mcp(mcp_server: dict):
    """T1:requirements.list / tasks.list 的 keyword、updated_within_days、逗号分隔多状态。

    旧 cursor 跨条件拒绝仍成立(keyword 变更 / 新增时间窗口均拒绝)。
    updated_within_days 排除语义:直连 e2e 库把行 updated_at 回拨 5 天验证。
    """
    import uuid
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session as SASession

    from app.models import Requirement as ReqModel

    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    pid = mcp_server["project_id"]

    r1 = client.call("requirements.create", project_id=pid, title="MCP Login 需求")
    client.call("requirements.set_status", id=r1["id"], status="backlog", project_id=mcp_server["project_id"])
    r2 = client.call("requirements.create", project_id=pid, title="MCP Pay 需求")
    client.call("requirements.set_status", id=r2["id"], status="in_progress", project_id=mcp_server["project_id"])
    r3 = client.call("requirements.create", project_id=pid, title="MCP 旧需求")

    # keyword:大小写不敏感,标题命中
    page = client.call("requirements.list", project_id=pid, keyword="login")
    assert [i["id"] for i in page["items"]] == [r1["id"]], page
    page = client.call("requirements.list", project_id=pid, keyword="LOGIN")
    assert [i["id"] for i in page["items"]] == [r1["id"]], page
    # keyword 无命中
    assert client.call("requirements.list", project_id=pid, keyword="zzz-nope")["items"] == []

    # 逗号分隔多状态
    page = client.call("requirements.list", project_id=pid, status="backlog,in_progress")
    ids = {i["id"] for i in page["items"]}
    assert r1["id"] in ids and r2["id"] in ids and r3["id"] not in ids, page
    # 单值不变
    page = client.call("requirements.list", project_id=pid, status="backlog")
    assert [i["id"] for i in page["items"]] == [r1["id"]], page

    # updated_within_days:回拨 r3 5 天 → 窗口 3 排除、窗口 30 包含
    # 共享 module 级 DB:上游用例(test_cursor_pagination_over_mcp)遗留 25 条 pending 需求,
    # r3 回拨后按 updated_at DESC 排到最末,默认 limit=20 会截断;故显式 limit=100 分页。
    db_path = mcp_server["log_file"].parent / "e2e.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"timeout": 10})
    with SASession(engine) as s:
        row = s.scalar(select(ReqModel).where(ReqModel.code == r3["id"]).limit(1))
        assert row is not None
        row.updated_at = datetime.now(timezone.utc) - timedelta(days=5)
        s.commit()
    engine.dispose()
    page = client.call("requirements.list", project_id=pid, updated_within_days=3, limit=100)
    assert r3["id"] not in {i["id"] for i in page["items"]}, page
    page = client.call("requirements.list", project_id=pid, updated_within_days=30, limit=100)
    assert r3["id"] in {i["id"] for i in page["items"]}, page
    # updated_within_days=0 → invalid_request
    err = client.call("requirements.list", project_id=pid, updated_within_days=0)
    assert "invalid_request" in err["error"], err

    # 旧 cursor 跨条件拒绝:keyword 变更 / 新增时间窗口
    page1 = client.call("requirements.list", project_id=pid, keyword="MCP", limit=1)
    assert page1["next_cursor"] is not None
    err = client.call("requirements.list", project_id=pid, keyword="pay", cursor=page1["next_cursor"])
    assert "invalid_request" in err["error"], err
    err = client.call(
        "requirements.list", project_id=pid, keyword="MCP", updated_within_days=3, cursor=page1["next_cursor"]
    )
    assert "invalid_request" in err["error"], err

    # tasks.list 同样三件套(任务必挂需求)
    t_mount = client.call("requirements.create", project_id=pid, title="MCP 任务挂载需求")
    client.call("requirements.set_status", id=t_mount["id"], status="backlog", project_id=mcp_server["project_id"])
    t1 = client.call(
        "tasks.create", project_id=pid, title="MCP Form 任务", requirement_id=t_mount["id"]
    )
    t2 = client.call(
        "tasks.create", project_id=pid, title="MCP Pay 任务", requirement_id=t_mount["id"]
    )
    client.call("tasks.set_status", id=t2["id"], status="in_progress", project_id=mcp_server["project_id"])
    page = client.call("tasks.list", project_id=pid, keyword="FORM")
    assert [i["id"] for i in page["items"]] == [t1["id"]], page
    page = client.call("tasks.list", project_id=pid, status="backlog,in_progress")
    assert {t1["id"], t2["id"]} <= {i["id"] for i in page["items"]}, page
    page = client.call("tasks.list", project_id=pid, updated_within_days=3)
    assert {t1["id"], t2["id"]} <= {i["id"] for i in page["items"]}, page

    # 清理本测试建的实体(恢复列表基线)
    client.call("tasks.delete", id=t1["id"], project_id=mcp_server["project_id"])
    client.call("tasks.delete", id=t2["id"], project_id=mcp_server["project_id"])
    for rid in (r1["id"], r2["id"], r3["id"], t_mount["id"]):
        client.call("requirements.delete", id=rid, confirm_task_count=0, project_id=mcp_server["project_id"])


def test_bad_key_rejected(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], "zc_invalid-key-0000000000")
    with pytest.raises(httpx.HTTPStatusError) as e:
        client.initialize()
    assert e.value.response.status_code == 401


@pytest.mark.parametrize("origin", ["codex://desktop", "null"])
def test_codex_origins_can_initialize_and_list_tools(mcp_server: dict, origin: str):
    """Codex 的非 HTTP Origin 也必须能通过本地 MCP 的传输安全校验。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"], origin=origin)
    init = client.initialize()
    assert init["serverInfo"]["name"] == "zeichen"
    assert "agent.whoami" in client.list_tools()


@pytest.mark.parametrize(
    "mcp_server",
    [{"MCP_ALLOWED_HOSTS": "mcp.zeichen.test:*"}],
    indirect=True,
)
def test_mcp_allowed_hosts_accepts_comma_separated_host_patterns(mcp_server: dict):
    """部署域名可通过 MCP_ALLOWED_HOSTS 加入 DNS-rebinding Host 白名单。"""
    port = mcp_server["url"].rsplit(":", 1)[1].removesuffix("/mcp")
    client = RawMcpClient(
        mcp_server["url"],
        mcp_server["token"],
        origin="codex://desktop",
        host=f"mcp.zeichen.test:{port}",
    )
    assert client.initialize()["serverInfo"]["name"] == "zeichen"


@pytest.mark.parametrize(
    "mcp_server",
    [{"MCP_ENABLE_DNS_REBINDING_PROTECTION": "false"}],
    indirect=True,
)
def test_mcp_can_explicitly_disable_dns_rebinding_protection(mcp_server: dict):
    """开关关闭后，Host/Origin 校验都不应再阻断客户端握手。"""
    port = mcp_server["url"].rsplit(":", 1)[1].removesuffix("/mcp")
    client = RawMcpClient(
        mcp_server["url"],
        mcp_server["token"],
        origin="https://untrusted-client.example",
        host=f"untrusted-client.example:{port}",
    )
    assert client.initialize()["serverInfo"]["name"] == "zeichen"


@pytest.mark.parametrize(
    "mcp_server",
    [
        {
            "MCP_ISSUER_URL": "https://zeichen.example.com/zeichen",
            "MCP_RESOURCE_SERVER_URL": "https://zeichen.example.com/mcp",
        }
    ],
    indirect=True,
)
def test_mcp_oauth_urls_configurable_via_settings(mcp_server: dict):
    """OAuth issuer / resource-server URL 必须可经 env 配置，元数据端点如实透出。

    Bearer-key 模式下 SDK 只挂载 protected-resource 元数据端点(RFC 9728):
    `resource` 反映 resource_server_url,`authorization_servers` 反映 issuer_url。
    """
    base = mcp_server["url"].rsplit("/mcp", 1)[0]
    with httpx.Client(timeout=10, trust_env=False) as client:
        resource = client.get(f"{base}/.well-known/oauth-protected-resource/mcp")
        resource.raise_for_status()
        body = resource.json()
        assert body["resource"] == "https://zeichen.example.com/mcp"
        assert body["authorization_servers"] == ["https://zeichen.example.com/zeichen"]
