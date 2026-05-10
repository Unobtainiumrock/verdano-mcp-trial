"""Settings loaded from .env via pydantic-settings.

`.env` resolution order (first existing file wins):
1. ``$VERDANO_PROJECT_ROOT/.env``
2. Walk up from this file's directory until we find a ``.env``
3. CWD fallback (pydantic-settings default)
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """Locate the .env file, preferring VERDANO_PROJECT_ROOT."""
    root_env = os.environ.get("VERDANO_PROJECT_ROOT")
    if root_env:
        candidate = Path(root_env) / ".env"
        if candidate.is_file():
            return str(candidate)

    anchor = Path(__file__).resolve().parent
    for parent in (anchor, *anchor.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
        if parent == parent.parent:
            break

    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        env_prefix="VERDANO_",
        extra="ignore",
    )

    erp_base_url: HttpUrl = Field(default=HttpUrl("https://erp.corvera.ai"))
    erp_api_key: SecretStr
    duckdb_path: str = Field(default=".local/verdano.duckdb")


def load_settings() -> Settings:
    return Settings()
