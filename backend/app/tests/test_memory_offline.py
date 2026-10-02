"""REQ-57 回归:记忆系统下线后的对外可观察面(REST)。

- 记忆与 cognee REST 端点全部 404(路由与注册已删)
- 搜索不再接受 memory 域(API 层显式 invalid_request)
- MCP 工具列表的 memory.* 缺席断言在 test_mcp_e2e.test_agent_claim_to_requirement_done
"""

from .conftest import login


def test_memory_rest_endpoints_are_gone(client, db, world):
    login(client, "admin", "admin-pass-1")
    pid = world["project"].id
    gets = [
        f"/api/projects/{pid}/memory",
        f"/api/projects/{pid}/memory/sessions",
        f"/api/projects/{pid}/memory?confirmed=true",
    ]
    for url in gets:
        assert client.get(url).status_code == 404, f"GET {url} 应随记忆系统下线返回 404"
    posts = [
        (f"/api/projects/{pid}/memory/remember", {"session_id": "s", "content": "x"}),
        (f"/api/projects/{pid}/memory/recall", {"query": "x"}),
        (f"/api/projects/{pid}/memory/improve", {"session_id": "s"}),
    ]
    for url, body in posts:
        assert client.post(url, json=body).status_code == 404, f"POST {url} 应随记忆系统下线返回 404"
    assert client.delete(f"/api/projects/{pid}/memory/data-1").status_code == 404


def test_cognee_configuration_endpoints_are_gone(client, db, world):
    login(client, "admin", "admin-pass-1")
    assert client.get("/api/cognee/configuration").status_code == 404
    assert client.get("/api/cognee/configuration/status").status_code == 404
    assert client.post("/api/cognee/configuration/restarts", json={"confirmed": True}).status_code == 404


def test_search_domain_valid_set_has_no_memory(client, db, world):
    login(client, "admin", "admin-pass-1")
    resp = client.get("/api/search", params={"q": "登录", "domain": "memory"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_request"
    assert "不支持的搜索域" in resp.json()["message"]
    ok = client.get("/api/search", params={"q": "登录", "domain": ["requirement", "task"]})
    assert ok.status_code == 200
