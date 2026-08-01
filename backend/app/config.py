from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Zeichen API"
    # 默认指向 docker compose 的 postgres;本地无容器时可用 sqlite 覆盖(仅开发/测试)
    database_url: str = "postgresql+psycopg://zeichen:zeichen@localhost:5432/zeichen"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
