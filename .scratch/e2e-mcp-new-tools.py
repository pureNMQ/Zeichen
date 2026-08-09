"""部署冒烟补充:验证 06 票新增的 MCP 工具 search.query / attachment.upload / attachment.download。

运行:python .scratch/e2e-mcp-new-tools.py
"""

import base64
import json
import sys
import uuid

import httpx

MCP = "http://localhost:8002/mcp"
API = "http://localhost:8001"
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
                           "clientInfo": {"name": "smoke2", "version": "0"}},
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
        with httpx.Client(timeout=60, trust_env=False) as client:
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
    # 1. 登录拿项目 id
    api = httpx.Client(base_url=API, timeout=30)
    r = api.post("/api/auth/login", json={"username": "puremi", "password": PUREMI_PASSWORD})
    pid = api.get("/api/projects").json()[0]["id"]

    # 2. 建 agent + key
    agent_name = f"smoke2-{uuid.uuid4().hex[:6]}"
    r = api.post("/api/agents", json={"username": agent_name, "project_grants": [{"project_id": pid, "role": "editor"}]})
    agent_id = r.json()["id"]
    token = api.post(f"/api/agents/{agent_id}/keys", json={"note": "smoke2"}).json()["token"]

    mcp = RawMcpClient(MCP, token)
    mcp.initialize()

    # 3. 建需求(供附件与搜索使用)
    req = mcp.call("requirements.create", project_id=pid, title="MCP 新工具冒烟", description="search/attachment 验证")
    rid = req["id"]
    print(f"[1] 需求已建: {rid}")

    # 4. attachment.upload(bytes 参数)
    print("[2] attachment.upload")
    raw = b"\x89PNG\r\n\x1a\n fake-image-bytes " * 20
    up = mcp.call("attachment.upload", project_id=pid, target_type="requirement",
                  target_id=rid, file_name="logo.png", data=base64.b64encode(raw).decode())
    check("upload 返回 id", "id" in up, str(up)[:120])
    aid = up.get("id")

    # 5. attachment.download
    print("[3] attachment.download")
    dl = mcp.call("attachment.download", attachment_id=aid)
    check("download 回读一致", dl.get("file_name") == "logo.png" and
          base64.b64decode(dl.get("content", "")) == raw, f"{dl.get('file_name')} size={dl.get('size')}")

    # 6. search.query
    print("[4] search.query")
    sq = mcp.call("search.query", query="MCP 新工具")
    items = sq.get("items", [])
    check("search.query 命中需求", any(i.get("domain") == "requirement" and i.get("id") == rid for i in items),
          f"{len(items)} 条: {[i['domain'] for i in items]}")

    # 7. 清理:软删需求(附件应级联软删)
    print("[5] 清理")
    mcp.call("requirements.delete", id=rid, confirm_task_count=0)
    listing = api.get(f"/api/targets/requirement/{rid}/attachments")
    check("父实体删除后附件软删", listing.json().get("items", []) == [], f"{listing.json().get('items')}")

    print()
    print(f"==== 结果: {len(passed)} 通过, {len(failed)} 失败 ====")
    if failed:
        print("失败项:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
