"""Intermediate "raw" types between adapter output and canonical entities.

The adapter cannot produce `CanonicalDemandLine` directly because converting
retailer-published units → ERP cases requires `case_pack` from the ERP product
master, which requires a resolved mapping. The pipeline composes:

    Adapter (CSV → RawDemandLine) → Resolver (RawDemandLine → MappingResult)
        → Converter (RawDemandLine + MappingResult → CanonicalDemandLine)

`RawDemandLine` carries everything except `quantity_cases`; the conversion
step computes it.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from verdano.canonical import RetailerCode, RetailerProductKey


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RawDemandLine(_Strict):
    """Adapter output prior to mapping resolution and case conversion."""

    retailer: RetailerCode
    iso_week: str
    retailer_key: RetailerProductKey
    location_label: str
    raw_quantity: int = Field(ge=0)
    raw_unit_mode: str
    """`"cases"` or `"units"` per the retailer spec."""

    promo_flag: bool = False
    notes: str | None = None
    inferred: bool = False


class RawActualsLine(_Strict):
    """Adapter output for EPOS / actuals.

    Unlike forecasts, EPOS is always in consumer units (eaches) by definition,
    so `quantity_units` is the canonical field directly. No conversion needed
    until the drift-detection layer (out of scope for the trial).
    """

    retailer: RetailerCode
    iso_week: str
    retailer_key: RetailerProductKey
    segment_label: str
    units_sold: int = Field(ge=0)
    sales_value_gbp: Decimal = Field(ge=0)
