"""stateless(无会话)模式行为验证(REQ 88e42bad-09e5-4600-a464-97b64cc98ca2)。

切换 stateless_http 后服务端必须满足:
1. initialize 不再签发 Mcp-Session-Id;
2. 无会话 id 的后续请求正常处理(客户端无需持有会话状态);
3. 携带陈旧/伪造会话 id 的请求被忽略而不是拒绝(Session not found 从此消失);
4. 认证仍逐请求生效(Bearer token 校验不随会话移除而放松)。
"""

import httpx
import pytest

from app.tests.test_mcp_e2e import RawMcpClient, mcp_server  # noqa: F401


def test_stateless_initialize_issues_no_session_id(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    init = client.initialize()
    assert init["serverInfo"]["name"] == "zeichen"
    assert client.session_id is None, "stateless 模式不应签发 Mcp-Session-Id"


def test_stateless_requests_work_without_session_id(mcp_server: dict):
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    assert client.session_id is None
    tools = client.list_tools()
    assert "agent.whoami" in tools
    me = client.call("agent.whoami")
    assert me["is_agent"] is True


def test_stateless_stale_session_id_is_ignored(mcp_server: dict):
    """DSH 等客户端可能仍持有旧会话 id:必须被忽略而不是返回 Session not found。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    client.session_id = "deadbeef" * 8
    tools = client.list_tools()
    assert "requirements.list" in tools
    assert client.call("project.list")[0]["id"] == mcp_server["project_id"]


def test_stateless_auth_enforced_per_request(mcp_server: dict):
    """认证逐请求生效:后续请求换错误 token 仍被 401 拒绝。"""
    client = RawMcpClient(mcp_server["url"], mcp_server["token"])
    client.initialize()
    client._headers["Authorization"] = "Bearer zc_invalid-key-0000000000"
    with pytest.raises(httpx.HTTPStatusError) as e:
        client.list_tools()
    assert e.value.response.status_code == 401
