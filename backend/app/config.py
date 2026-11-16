from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MCP_ALLOWED_HOSTS = "127.0.0.1:*,localhost:*,[::1]:*"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Zeichen API"
    # 默认指向 docker compose 的 postgres;本地无容器时可用 sqlite 覆盖(仅开发/测试)
    database_url: str = "postgresql+psycopg://zeichen:zeichen@localhost:5432/zeichen"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Public Web origin. Password-setup links must target the SPA, never the
    # API process listening behind the development proxy.
    web_base_url: str = "http://localhost:5173"

    # 会话 JWT 密钥与 cookie 名(生产必须经 env 覆盖)
    session_secret: str = "dev-only-session-secret-change-me-0123456789abcdef"
    session_cookie_name: str = "zeichen_session"
    session_ttl_seconds: int = 7 * 24 * 3600
    session_cookie_secure: bool = False

    attachment_storage_dir: Path = Path(".scratch/attachments")
    attachment_max_bytes: int = 20 * 1024 * 1024

    # Streamable HTTP MCP: DNS-rebinding protection remains enabled by default.
    # Use a comma-separated string so a normal .env file can safely extend the
    # Host allowlist for an externally deployed MCP endpoint.
    mcp_enable_dns_rebinding_protection: bool = True
    mcp_allowed_hosts: str = DEFAULT_MCP_ALLOWED_HOSTS
    # MCP OAuth metadata URLs (spec §4.1: bearer-key only, no interactive flow,
    # but the protected-resource metadata endpoint advertises both).  A public
    # deployment must point these at its external HTTPS base, e.g.
    # MCP_ISSUER_URL=https://zeichen.example.com/zeichen and
    # MCP_RESOURCE_SERVER_URL=https://zeichen.example.com/mcp.
    mcp_issuer_url: str = "http://localhost/zeichen"
    mcp_resource_server_url: str = "http://localhost/mcp"

    # 附件存储(规格书 §8.2):单文件 20MB、单项目配额 2GB;本地目录按项目分桶
    attachment_storage_dir: str = "storage/attachments"
    attachment_max_file_bytes: int = 20 * 1024 * 1024
    attachment_project_quota_bytes: int = 2 * 1024 * 1024 * 1024

    # v2 file-library limits are separately configurable from legacy attachments.
    file_library_max_file_bytes: int = Field(default=256 * 1024 * 1024, gt=0)
    file_library_project_quota_bytes: int = Field(default=4 * 1024 * 1024 * 1024, gt=0)
    file_library_grant_ttl_seconds: int = Field(default=15 * 60, gt=0)

    # 软删实体物理清理定时任务(REQ-3 / 规格书 §2.1 / §8.2):
    # 软删满 retention_days 天的实体由定时任务物理清理(恰好满期即清,<= 判定);
    # 清理循环按 interval_seconds 周期执行(默认 24h)。env:PHYSICAL_PURGE_RETENTION_DAYS
    # / PHYSICAL_PURGE_INTERVAL_SECONDS。
    physical_purge_retention_days: int = 90
    physical_purge_interval_seconds: float = 24 * 60 * 60

    @property
    def mcp_allowed_host_patterns(self) -> list[str]:
        """Return the non-empty comma-separated MCP Host allowlist entries."""
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
