"""Drift-signal record carrying provenance for the operator UI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from verdano.canonical import RetailerCode, RetailerProductKey

DriftDirection = Literal["high", "low", "ok"]
"""`high`: forecast >> lagged actuals (over-forecast risk).
`low`: forecast << lagged actuals (under-forecast risk).
`ok`: ratio within bounds, OR promo-segmented (excluded from threshold)."""


class DriftSignal(BaseModel):
    """A single (retailer, sku, weekpair) drift result.

    Per D-012, the underlying math is a ratio not a residual:

        ratio = forecast_eaches / max(actuals_eaches, 1)

    A ratio of 1.0 means forecast and lagged actuals are equal in eaches.
    Thresholds default to [0.5, 1.5]; outside that range, `direction` flags
    the side of the deviation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    retailer: RetailerCode
    iso_week_forecast: str
    iso_week_actuals: str
    erp_sku: str
    retailer_key: RetailerProductKey
    forecast_eaches: int = Field(ge=0)
    actuals_eaches: int = Field(ge=0)
    ratio: float = Field(ge=0.0)
    direction: DriftDirection
    promo_flag: bool = False
    """The forecast row's declared promo state (False if retailer doesn't publish a flag)."""

    promo_segmented: bool = False
    """True iff this signal was excluded from threshold-based flagging because
    it sits on a promo period (Tesco only — Sainsbury's has no promo column)."""

    reason: str
