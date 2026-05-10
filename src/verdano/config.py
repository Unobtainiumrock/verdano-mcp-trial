"""Settings loaded from .env via pydantic-settings.

`.env` resolution order (first existing file wins):
1. ``$VERDANO_PROJECT_ROOT/.env``
2. Walk up from this file's directory until we find a ``.env``
3. CWD fallback (pydantic-settings default)
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, model_validator
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

    # --- ERP connection ---
    erp_base_url: HttpUrl = Field(default=HttpUrl("https://erp.corvera.ai"))
    erp_api_key: SecretStr
    duckdb_path: str = Field(default=".local/verdano.duckdb")

    # --- Classification thresholds ---
    tau_safe: float = Field(default=0.90, ge=0.0, le=1.0)
    auto_threshold: float = Field(default=0.90, ge=0.0, le=1.0)

    # --- Cascade resolver ---
    tfidf_min_score: float = Field(default=0.5, ge=0.0, le=1.0)
    tfidf_min_matched_tokens: int = Field(default=2, ge=1)
    fuzzy_jw_min_score: float = Field(default=0.30, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _compat_e4_min_score(cls, values: dict) -> dict:  # type: ignore[type-arg]
        """Accept legacy VERDANO_E4_MIN_SCORE as an alias."""
        legacy = values.get("e4_min_score")
        if legacy is not None and values.get("fuzzy_jw_min_score") is None:
            values["fuzzy_jw_min_score"] = legacy
        return values

    # --- Fellegi-Sunter priors ---
    fs_epsilon: float = Field(default=0.02, ge=0.0, le=1.0)
    fs_gamma: float = Field(default=0.10, ge=0.0, le=1.0)
    fs_alpha: float = Field(default=1.5, gt=0.0)

    # --- Drift thresholds ---
    drift_threshold_low: float = Field(default=0.5, gt=0.0, lt=1.0)
    drift_threshold_high: float = Field(default=1.5, gt=1.0)

    # --- Depot resolver ---
    depot_fuzzy_threshold: int = Field(default=75, ge=0, le=100)

    # --- LLM integration (optional) ---
    llm_provider: str = Field(default="openai")
    llm_model: str = Field(default="gpt-4o")
    llm_api_key: SecretStr = Field(default=SecretStr(""))
    llm_base_url: str = Field(default="https://api.openai.com/v1")


def load_settings() -> Settings:
    return Settings()
