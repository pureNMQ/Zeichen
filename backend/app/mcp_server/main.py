"""MCP server 组装与启动(规格书 §4.1:单 server + Streamable HTTP + Bearer key)。

运行:python -m app.mcp_server(内部 uvicorn),端点 /mcp;
或外部托管 uvicorn app.mcp_server:app。
"""

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from .auth import ApiKeyTokenVerifier

mcp = FastMCP(
    "zeichen",
    instructions=(
        "贼船 Zeichen 项目协同 MCP 服务。认证:Bearer API key(仅 agent 签发)。"
        "错误四件套:permission_denied / not_found / conflict / invalid_request,"
        "以 `code: message` 前缀出现在工具错误中。"
    ),
    auth=AuthSettings(
        issuer_url="http://localhost/zeichen",
        resource_server_url="http://localhost/mcp",
    ),
    token_verifier=ApiKeyTokenVerifier(),
)

from . import tools  # noqa: E402

tools._register_all(mcp)

app = mcp.streamable_http_app()


def run() -> None:
    mcp.run(transport="streamable-http")
