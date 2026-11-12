from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SMART TRADING PRO API"
    environment: str = "development"
    api_prefix: str = "/api/v2"
    database_url: str | None = None
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    request_timeout_seconds: float = 8.0

    @property
    def production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.production and not settings.database_url:
        raise RuntimeError("DATABASE_URL is required in production; refusing ephemeral storage.")
    if settings.production and settings.database_url and settings.database_url.startswith("sqlite"):
        raise RuntimeError("SQLite is disabled in production; configure durable PostgreSQL.")
    return settings
