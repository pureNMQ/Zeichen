from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Zeichen API"
    # 默认指向 docker compose 的 postgres;本地无容器时可用 sqlite 覆盖(仅开发/测试)
    database_url: str = "postgresql+psycopg://zeichen:zeichen@localhost:5432/zeichen"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # 会话 JWT 密钥与 cookie 名(生产必须经 env 覆盖)
    session_secret: str = "dev-only-session-secret-change-me-0123456789abcdef"
    session_cookie_name: str = "zeichen_session"
    session_ttl_seconds: int = 7 * 24 * 3600
    session_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
