"""MCP server 组装与启动(规格书 §4.1:单 server + Streamable HTTP + Bearer key)。

运行:python -m app.mcp_server(内部 uvicorn),端点 /mcp;
或外部托管 uvicorn app.mcp_server:app。
"""

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import get_settings

from .auth import ApiKeyTokenVerifier

settings = get_settings()

mcp = FastMCP(
    "zeichen",
    instructions=(
        "贼船 Zeichen 项目协同 MCP 服务。认证:Bearer API key(仅 agent 签发)。"
        "错误四件套:permission_denied / not_found / conflict / invalid_request,"
        "以 `code: message` 前缀出现在工具错误中。"
    ),
    auth=AuthSettings(
        issuer_url=settings.mcp_issuer_url,
        resource_server_url=settings.mcp_resource_server_url,
    ),
    token_verifier=ApiKeyTokenVerifier(),
    # 无会话(stateless)模式(REQ 88e42bad):服务端不创建/维护 MCP 会话,每个请求
    # 独立处理。消除进程重启(uvicorn --reload 重载、容器重建、升级)导致客户端
    # 会话失效、工具调用持续 Session not found 的问题;认证仍逐请求校验。
    stateless_http=True,
    # Keep DNS-rebinding protection enabled by default. MCP_ALLOWED_HOSTS lets
    # a reverse-proxied deployment explicitly allow its public Host header;
    # MCP_ENABLE_DNS_REBINDING_PROTECTION=false is an intentional opt-out for
    # deployments where an upstream proxy performs equivalent validation.
    # Codex uses opaque origins for its local Streamable HTTP client, so retain
    # its two known origins while every request still requires a Bearer API key.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=settings.mcp_enable_dns_rebinding_protection,
        allowed_hosts=settings.mcp_allowed_host_patterns,
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            "codex://desktop",
            "null",
        ],
    ),
)

from . import tools  # noqa: E402
from .file_tools import register_file_tools  # noqa: E402
from .wiki_tools import register_wiki_tools  # noqa: E402

tools._register_all(mcp)
register_file_tools(mcp)
register_wiki_tools(mcp)

app = mcp.streamable_http_app()


def run() -> None:
    mcp.run(transport="streamable-http")
