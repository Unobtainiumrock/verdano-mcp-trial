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
    def _compat_aliases(cls, values: dict) -> dict:  # type: ignore[type-arg]
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
    drift_residual_threshold: float = Field(
        default=0.10, ge=0.0, le=1.0,
        description="Residual-mode tolerance: abs(pct_error) within this is 'accurate'.",
    )

    # --- Markov drift (D-024) ---
    drift_markov_min_weeks: int = Field(
        default=4, ge=2,
        description="Minimum weeks of residual history before Markov analysis runs.",
    )
    drift_markov_persistence_threshold: int = Field(
        default=3, ge=2,
        description="Consecutive non-accurate weeks to flag persistence.",
    )
    drift_markov_max_weeks: int = Field(
        default=52, ge=4,
        description="Maximum weeks of history to load per SKU (caps query cost).",
    )

    # --- Normalization (D-023) ---
    normalize_brand_stripping: bool = Field(default=False)
    brand_prefixes: str = Field(
        default="verdano,verdano foods",
        description="Comma-separated brand prefixes to strip (lowercased).",
    )
    normalize_stop_words: bool = Field(default=False)
    stop_words: str = Field(
        default="the,and,with,pack,of,for",
        description="Comma-separated stop words to remove.",
    )

    # --- Confidence hooks (D-022) ---
    temp_band_penalty_enabled: bool = Field(default=False)
    temp_band_penalty_lambda: float = Field(
        default=0.3, gt=0.0, le=1.0,
        description="Multiplicative penalty when temperature-band keywords mismatch.",
    )

    # --- Depot resolver ---
    depot_fuzzy_threshold: int = Field(default=75, ge=0, le=100)
    depot_llm_min_confidence: float = Field(default=0.50, ge=0.0, le=1.0)

    # --- LLM integration (optional) ---
    llm_model: str = Field(default="gpt-4o")
    llm_api_key: SecretStr = Field(default=SecretStr(""))
    llm_base_url: str = Field(default="https://api.openai.com/v1")

    # --- LLM re-ranker (D-019) ---
    rerank_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    rerank_strata: str = Field(default="tfidf_overlap,fuzzy_jw")
    rerank_min_llm_confidence: float = Field(default=0.70, ge=0.0, le=1.0)

    def get_rerank_strata(self) -> frozenset[str]:
        """Parse comma-separated stratum names into a frozenset."""
        return frozenset(s.strip() for s in self.rerank_strata.split(",") if s.strip())

    def get_brand_prefixes(self) -> set[str] | None:
        """Return brand prefixes if stripping is enabled, else None."""
        if not self.normalize_brand_stripping:
            return None
        return {s.strip() for s in self.brand_prefixes.split(",") if s.strip()}

    def get_stop_words(self) -> set[str] | None:
        """Return stop words if removal is enabled, else None."""
        if not self.normalize_stop_words:
            return None
        return {s.strip() for s in self.stop_words.split(",") if s.strip()}


def load_settings() -> Settings:
    return Settings()
