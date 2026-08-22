from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    database_url: str = Field(
        default="postgresql://app:app@localhost:5432/app", validation_alias="DATABASE_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    allowed_origins_csv: str = Field(
        default="http://localhost:5173", validation_alias="APP_ALLOWED_ORIGINS"
    )
    session_cookie_secure: bool = Field(
        default=False, validation_alias="APP_SESSION_COOKIE_SECURE"
    )
    session_ttl_seconds: int = Field(
        default=60 * 60 * 24 * 14, ge=300, validation_alias="APP_SESSION_TTL_SECONDS"
    )

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset(
            value.strip()
            for value in self.allowed_origins_csv.split(",")
            if value.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
