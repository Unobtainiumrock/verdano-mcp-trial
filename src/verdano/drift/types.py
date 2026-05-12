"""Drift-signal record carrying provenance for the operator UI.

Supports multiple drift modes (D-020, D-024):
- ``plausibility``: ratio-based lagged-actuals check (D-012)
- ``residual``: classical signed residual for same-period comparison
- ``markov``: regime-detection via transition-matrix analysis (D-024)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from verdano.canonical import RetailerCode, RetailerProductKey

# ---------------------------------------------------------------------------
# DriftDirection: runtime-extensible (D-020, mirrors D-016 pattern)
# ---------------------------------------------------------------------------

DriftDirection = str
"""Runtime-extensible drift direction identifier."""

_DRIFT_DIRECTION_REGISTRY: set[str] = set()


def register_drift_direction(d: str) -> None:
    """Register a drift direction as valid."""
    _DRIFT_DIRECTION_REGISTRY.add(d)


def known_drift_directions() -> frozenset[str]:
    return frozenset(_DRIFT_DIRECTION_REGISTRY)


for _d in ("high", "low", "ok"):
    register_drift_direction(_d)


class DriftSignal(BaseModel):
    """A single (retailer, sku, weekpair) drift result.

    Supports multiple analysis modes via the ``mode`` discriminator:

    - **plausibility** (D-012): ``ratio = forecast_eaches / max(actuals_eaches, 1)``
    - **residual** (D-020): ``residual = actuals_eaches - forecast_eaches``
    - **markov** (D-024): regime-detection via transition-matrix analysis

    Common fields (``forecast_eaches``, ``actuals_eaches``, ``direction``,
    ``reason``) are always populated. Mode-specific fields are ``None`` when
    the signal was produced by a different mode.
    """

    model_config = ConfigDict(frozen=True)

    mode: str = "plausibility"
    retailer: RetailerCode
    iso_week_forecast: str
    iso_week_actuals: str
    erp_sku: str
    retailer_key: RetailerProductKey
    forecast_eaches: int = Field(ge=0)
    actuals_eaches: int = Field(ge=0)

    ratio: float | None = None
    """Plausibility mode: forecast / max(actuals, 1). None in residual mode."""

    residual: int | None = None
    """Residual mode: actuals - forecast (signed). None in plausibility mode."""

    pct_error: float | None = None
    """Residual mode: residual / max(forecast, 1). None in plausibility mode."""

    direction: DriftDirection
    promo_flag: bool = False
    promo_segmented: bool = False
    reason: str

    persistence_weeks: int | None = None
    """Markov mode: consecutive weeks in current non-accurate state."""

    transition_probability: float | None = None
    """Markov mode: P(staying in current state) from the transition matrix."""
