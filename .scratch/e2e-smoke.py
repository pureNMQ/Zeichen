"""本地部署端到端冒烟:登录 → 建 agent+key → agent 经 MCP 建需求 → 通知 → 搜索 → 附件。

运行:python .scratch/e2e-smoke.py (需 API/MCP/cognee 在线)
"""

import base64
import json
import sys
import uuid

import httpx

API = "http://localhost:8001"
MCP = "http://localhost:8002/mcp"
PUREMI_PASSWORD = "123456789"

passed, failed = [], []


def check(name, ok, detail=""):
    if ok:
        passed.append(name)
        print(f"  PASS  {name} {detail}")
    else:
        failed.append(name)
        print(f"  FAIL  {name} {detail}")


def parse_sse(body: str) -> list[dict]:
    msgs = []
    for block in body.split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data:")]
        if data:
            msgs.append(json.loads("\n".join(data)))
    return msgs


class RawMcpClient:
    """最小 MCP streamable-http 客户端(与 test_mcp_e2e 同构)。"""

    def __init__(self, url: str, token: str):
        self.url = url
        self.session_id: str | None = None
        self._id = 0
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        }

    def initialize(self) -> dict:
        return self._post("initialize",
                          {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "smoke", "version": "0"}},
                          is_initialize=True)

    def call(self, tool_name: str, **arguments) -> dict:
        result = self._post("tools/call", {"name": tool_name, "arguments": arguments})
        if "error" in result:
            return result
        if result.get("isError"):
            texts = [c.get("text", "") for c in result.get("content", [])]
            return {"error": " ".join(texts).strip()}
        texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
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
        with httpx.Client(timeout=30, trust_env=False) as client:
            resp = client.post(self.url, headers=headers, json=payload)
            resp.raise_for_status()
            if is_initialize:
                sid = resp.headers.get("mcp-session-id")
                if sid:
                    self.session_id = sid
            msgs = parse_sse(resp.text)
        if not msgs:
            raise RuntimeError(f"无 SSE 响应: {method} {resp.status_code}")
        msg = msgs[0]
        if "error" in msg:
            return {"error": msg["error"]["message"]}
        return msg["result"]


def main():
    # ---------- 1. puremi 登录 ----------
    print("[1] 登录 puremi")
    api = httpx.Client(base_url=API, timeout=30)
    r = api.post("/api/auth/login", json={"username": "puremi", "password": PUREMI_PASSWORD})
    check("登录", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    me = r.json().get("user") or {}
    print(f"       user={me.get('username')} role={me.get('workspace_role')}")

    # ---------- 2. 项目列表 ----------
    r = api.get("/api/projects")
    check("项目列表", r.status_code == 200, f"{len(r.json())} 个项目")
    projects = r.json()
    target_project = projects[0] if projects else None
    if not target_project:
        print("       !! 无项目,中止"); sys.exit(1)
    pid = target_project["id"]
    print(f"       项目: {target_project['name']} ({pid})")

    # ---------- 3. 建 agent + 签发 key ----------
    print("[2] 建测试 agent 并签发 key")
    agent_name = f"smoke-{uuid.uuid4().hex[:6]}"
    r = api.post("/api/agents", json={"username": agent_name, "project_grants": [{"project_id": pid, "role": "editor"}]})
    check("建 agent", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
    agent_id = r.json().get("id")
    r = api.post(f"/api/agents/{agent_id}/keys", json={"note": "smoke test key"})
    check("签发 key", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
    token = r.json().get("token")
    check("key 明文返回", bool(token), f"token={token[:12]}..." if token else "")

    # ---------- 4. MCP 握手 + agent 建需求 ----------
    print("[3] agent 经 MCP 建需求")
    mcp = RawMcpClient(MCP, token)
    try:
        init = mcp.initialize()
        check("MCP initialize", init.get("serverInfo", {}).get("name") == "zeichen", str(init)[:120])
    except Exception as e:
        check("MCP initialize", False, str(e)[:200])
        init = None

    title = f"部署冒烟需求-{uuid.uuid4().hex[:6]}"
    req_id = None
    if init:
        call = mcp.call("requirements.create", project_id=pid, title=title, description="本地部署端到端验证")
        if "error" in call:
            check("MCP requirements.create", False, str(call)[:200])
        else:
            req_id = call.get("id")
            check("MCP requirements.create", bool(req_id), f"id={req_id}")
            print(f"       需求 id: {req_id}")
            tools = mcp._post("tools/list", {})
            names = [t["name"] for t in tools.get("tools", [])]
            check("MCP 含新工具", all(n in names for n in ("search.query", "attachment.upload", "attachment.download")),
                  f"{len(names)} 个工具")
    else:
        check("MCP requirements.create", False, "initialize 失败")

    # ---------- 5. puremi 通知验证 ----------
    print("[4] 通知验证(agent 建需求 → puremi 是 owner 应收到)")
    r = api.get("/api/notifications/unread-count")
    count = r.json().get("count", 0)
    check("未读通知数 > 0", count > 0, f"count={count}")
    r = api.get("/api/notifications")
    items = r.json().get("items", [])
    check("通知列表含需求创建", any(i.get("target_type") == "requirement" for i in items), f"{len(items)} 条")

    # ---------- 6. 搜索验证 ----------
    print("[5] 全局搜索")
    r = api.get(f"/api/search", params={"q": "冒烟"})
    check("搜索需求命中", r.status_code == 200 and any(i["domain"] == "requirement" and title in i["title"] for i in r.json().get("items", [])),
          f"HTTP {r.status_code} {len(r.json().get('items', []))} 条")

    # ---------- 7. 附件验证 ----------
    print("[6] 附件上传/下载")
    if req_id:
        r = api.post(f"/api/targets/requirement/{req_id}/attachments",
                     files={"file": ("smoke.txt", b"deploy-smoke-content", "text/plain")})
        check("附件上传", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
        aid = r.json().get("id")
        r = api.get(f"/api/attachments/{aid}/download")
        check("附件下载", r.status_code == 200 and r.content == b"deploy-smoke-content", f"HTTP {r.status_code} {r.content[:40]}")
        r = api.get(f"/api/targets/requirement/{req_id}/attachments")
        check("附件列表", len(r.json().get("items", [])) == 1, f"{len(r.json().get('items', []))} 条")

    # ---------- 8. 已读 ----------
    print("[7] 通知已读")
    r = api.post("/api/notifications/read-all")
    check("全部已读", r.status_code == 200)
    r = api.get("/api/notifications/unread-count")
    check("未读清零", r.json().get("count", -1) == 0, f"count={r.json().get('count')}")

    print()
    print(f"==== 结果: {len(passed)} 通过, {len(failed)} 失败 ====")
    if failed:
        print("失败项:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
