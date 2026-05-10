"""Retailer adapter specs.

The spec is a Pydantic config object that declares column mappings, time/unit
semantics, and a default disaggregation kernel. The single `Adapter` class
(see `adapter.py`) uses the spec to convert retailer CSVs into canonical
entities.

Adding a new retailer = adding a new `RetailerSpec` instance. No new code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from verdano.canonical import RetailerCode

UnitMode = Literal["cases", "units"]
"""Whether the retailer publishes forecasts in cases or consumer units.
`units` triggers ceiling division by `case_pack` during normalization."""


TimeMode = Literal["daily", "iso_week"]
"""Whether the time column is a per-day delivery date or an ISO-week aggregate."""


# Per D-009: UK-grocery DOW profile (Mon→Sun). Locked default for retailers
# without historical EPOS. Override at the spec level if a retailer has data.
DOW7 = tuple[float, float, float, float, float, float, float]
DEFAULT_DOW_KERNEL: DOW7 = (0.10, 0.10, 0.10, 0.15, 0.25, 0.20, 0.10)


class DOWKernel(BaseModel):
    """Day-of-week disaggregation kernel (per D-009).

    `weights` is a 7-tuple summing to 1.0; index 0 is Monday. When an
    aggregate weekly row needs disaggregation to daily, multiply by these
    weights. The trial-scope default is the static UK-grocery profile.
    """

    model_config = ConfigDict(frozen=True)

    weights: DOW7 = Field(default=DEFAULT_DOW_KERNEL)

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        s = sum(self.weights)
        if abs(s - 1.0) > 1e-6:
            raise ValueError(f"DOW kernel must sum to 1.0; got {s}")


class ForecastColumns(BaseModel):
    """Column-name mapping from CSV headers to canonical fields.

    Set fields to `None` if the retailer doesn't publish that column (e.g.,
    Sainsbury's has no `promo_flag` — known-unknown).
    """

    model_config = ConfigDict(frozen=True)

    time: str
    """The CSV column with the time value (per `time_mode`)."""

    name: str
    """Free-text product name."""

    location: str
    """Free-text location label (depot, geography, etc)."""

    quantity: str
    """The CSV column with the demand quantity (per `unit_mode`)."""

    gtin: str | None = None
    tesco_item: str | None = None
    promo_flag: str | None = None
    notes: str | None = None


class ActualsColumns(BaseModel):
    """Column mapping for EPOS / actuals CSVs."""

    model_config = ConfigDict(frozen=True)

    time: str
    name: str
    segment: str
    """Channel / store group — retailer-specific."""

    units_sold: str
    sales_value: str
    gtin: str | None = None
    tesco_item: str | None = None


class RetailerSpec(BaseModel):
    """Declarative retailer adapter spec.

    The single `Adapter` class consumes this spec and produces canonical
    entities from CSVs without retailer-specific code paths.
    """

    model_config = ConfigDict(frozen=True)

    code: RetailerCode
    forecast: ForecastColumns
    actuals: ActualsColumns
    forecast_unit_mode: UnitMode
    forecast_time_mode: TimeMode
    actuals_unit_mode: Literal["units"] = "units"
    """EPOS is always consumer units (eaches) by definition."""

    promo_flag_truthy: tuple[str, ...] = ("Y", "y", "yes", "true", "1", "True")
    """Strings the retailer uses for "promo on". Tesco uses 'Y'; Sainsbury's
    has no flag column — leave default."""

    dow_kernel: DOWKernel = Field(default_factory=DOWKernel)
    """For weekly→daily disaggregation. Trial default is the UK-grocery profile."""


# ---------------------------------------------------------------------------
# Concrete specs — one per retailer fixture in the trial.
# Adding a third retailer = a third instance below; no other code changes.
# ---------------------------------------------------------------------------

TESCO_SPEC = RetailerSpec(
    code="tesco",
    forecast_unit_mode="cases",
    forecast_time_mode="daily",
    forecast=ForecastColumns(
        time="delivery_date",
        name="product_description",
        location="depot",
        quantity="forecast_cases",
        tesco_item="tesco_item",
        promo_flag="promo_flag",
        notes="notes",
    ),
    actuals=ActualsColumns(
        time="week_ending",
        name="product_description",
        segment="store_group",
        units_sold="eaches_sold",
        sales_value="sales_value_gbp",
        tesco_item="tesco_item",
    ),
)

SAINSBURYS_SPEC = RetailerSpec(
    code="sainsburys",
    forecast_unit_mode="units",
    forecast_time_mode="iso_week",
    forecast=ForecastColumns(
        time="receipt_week",
        name="item_name",
        location="geography",
        quantity="forecast_units",
        gtin="gtin",
    ),
    actuals=ActualsColumns(
        time="week",
        name="item_name",
        segment="channel",
        units_sold="units_sold",
        sales_value="net_sales_gbp",
        gtin="gtin",
    ),
)


_REGISTRY: dict[RetailerCode, RetailerSpec] = {
    "tesco": TESCO_SPEC,
    "sainsburys": SAINSBURYS_SPEC,
}


def get_spec(retailer: RetailerCode) -> RetailerSpec:
    """Look up the registered spec for a retailer code."""
    return _REGISTRY[retailer]
