from functools import lru_cache

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

    # The backend is normally run on the host by start-all.ps1, while Cognee is
    # published by Docker Compose on localhost:8000. A future in-compose backend
    # must override this with http://cognee:8000/api/v1.
    cognee_base_url: str = "http://localhost:8000/api/v1"
    cognee_timeout_seconds: float = 30.0
    # The durable improve worker, not an MCP request, owns this longer wait.
    # A timeout is recorded as unknown/timed_out and is never auto-retried,
    # because Cognee 1.4.1 may still be executing remotely.
    cognee_improve_job_timeout_seconds: float = 15 * 60
    cognee_improve_worker_poll_seconds: float = 1.0
    # Cognee runs with backend access control enabled.  The API process is the
    # sole Cognee principal: project roles are enforced by this application,
    # never delegated to browser or MCP clients.  Deployments should prefer a
    # long-lived API key; the email/password pair bootstraps the local service
    # account when a key has not been provisioned yet.
    cognee_service_api_key: str | None = None
    cognee_service_email: str = "zeichen-service@example.com"
    cognee_service_password: str = "zeichen-local-cognee-service-password"

    # Streamable HTTP MCP: DNS-rebinding protection remains enabled by default.
    # Use a comma-separated string so a normal .env file can safely extend the
    # Host allowlist for an externally deployed MCP endpoint.
    mcp_enable_dns_rebinding_protection: bool = True
    mcp_allowed_hosts: str = DEFAULT_MCP_ALLOWED_HOSTS

    @property
    def mcp_allowed_host_patterns(self) -> list[str]:
        """Return the non-empty comma-separated MCP Host allowlist entries."""
        return [host.strip() for host in self.mcp_allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
