"""Settings loaded from .env via pydantic-settings."""

from __future__ import annotations

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VERDANO_",
        extra="ignore",
    )

    erp_base_url: HttpUrl = Field(default=HttpUrl("https://erp.corvera.ai"))
    erp_api_key: SecretStr
    duckdb_path: str = Field(default=".local/verdano.duckdb")


def load_settings() -> Settings:
    return Settings()
