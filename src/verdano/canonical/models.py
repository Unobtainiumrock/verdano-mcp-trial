"""Canonical entity contracts.

The morphism domains/codomains from formalism §2. These are the *single*
representation that downstream pipeline stages consume — adapter outputs
must conform to these regardless of retailer source shape.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RetailerCode = Literal["tesco", "sainsburys"]
"""Closed enum at trial scope; the adapter spec system (D-001) extends this
without code change in production."""


Stratum = Literal["E1", "E2", "E3", "E3b", "E4"]
"""The cascade discovery strata, in firing order:

  E1   — exact match on `current_gtins`
  E2   — exact match on `legacy_gtins`
  E3   — exact match on canonicalized aliases / canonical name
  E3b  — TF-IDF token-overlap on the ERP master vocabulary (per D-013)
  E4   — Jaro-Winkler² on canonicalized name (fallback)

Per D-011, the cascade governs *discovery order* only; scores are independent
of stratum-of-origin. Each stratum produces a probabilistic score on its own
merit."""


MappingState = Literal["Resolved", "NeedsVerification", "Unmapped"]
"""Three review states (formalism §3.3). Operationally distinct: Resolved
auto-maps, NeedsVerification surfaces a candidate to verify, Unmapped surfaces
a retailer line with no candidate at all."""


FulfillmentClass = Literal[
    "Safe", "AtRisk", "AtRiskSevere", "NeedsVerification", "Blocked",
]
"""Per D-010 + formalism §5.3.3.
NeedsVerification: mapping produced a candidate but below auto-threshold.
Blocked: no mapping candidate at all (upstream of FTP).
AtRiskSevere: supply-constrained tripwire from D-010."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetailerProductKey(_Strict):
    """The retailer-side product identifier as published, prior to mapping.

    Different retailers populate different fields. Tesco gives `tesco_item`;
    Sainsbury's gives `gtin` + `name`. `name` always carries the free-text
    string for fuzzy matching.
    """

    retailer: RetailerCode
    name: str
    gtin: str | None = None
    tesco_item: str | None = None


class MappingEvidence(_Strict):
    """Provenance for a single mapping edge.

    Records *which stratum fired* and *what value matched*. The operator UI
    surfaces this as the `[Tag: Exact GTIN]` lineage indicator orthogonally
    to the confidence score (per Gemini iteration 9).
    """

    stratum: Stratum
    matched_value: str
    """The retailer-supplied string that matched (a GTIN, alias, or name)."""

    collision_count: int = Field(ge=1)
    """K_x — the number of distinct ERP SKUs sharing this matched value.
    Used in the Fellegi-Sunter posterior. K_x = 1 is fully unambiguous."""


class MappingResult(_Strict):
    """Output of the mapping resolver for a single retailer key.

    Per formalism §3.4: the mapping result is a triple ⟨edge, weight, evidence⟩.
    Confidence is a calibrated probability under the Fellegi-Sunter model
    (D-011, exact strata) or JW² (D-011, fuzzy stratum).
    """

    retailer_key: RetailerProductKey
    erp_sku: str | None
    """None when state == Unmapped."""

    confidence: float = Field(ge=0.0, le=1.0)
    state: MappingState
    evidence: MappingEvidence | None = None
    """None when state == Unmapped (no edge, hence no evidence)."""


class CanonicalDemandLine(_Strict):
    """Normalized retailer forecast row.

    Time grain is always ISO week (per D-007 — the comparison tool operates
    at week-level; daily Tesco rows are aggregated, weekly Sainsbury's pass
    through). Quantity is always in cases (per D-007 — units → cases via
    case_pack).
    """

    retailer: RetailerCode
    iso_week: str
    """Format: '2026-W20' per ISO 8601."""

    retailer_key: RetailerProductKey
    location_label: str
    """Free-text retailer label ('Daventry Chilled', 'All Depots', etc).
    Mapped to ERP `ship_to_location_id` separately by the location resolver."""

    quantity_cases: int = Field(ge=0)
    promo_flag: bool = False
    notes: str | None = None
    inferred: bool = False
    """True when this row was disaggregated from a coarser grain via a kernel
    (per D-007). False when published directly at this grain."""


class CanonicalActualsLine(_Strict):
    """Normalized retailer EPOS / actuals row.

    Quantity in *consumer units* (eaches), not cases — EPOS is point-of-sale
    where consumers buy individual units. Conversion to cases via `case_pack`
    happens in the drift-detection layer if needed.
    """

    retailer: RetailerCode
    iso_week: str
    retailer_key: RetailerProductKey
    segment_label: str
    """Channel / store group / depot — free-text retailer segmentation."""

    units_sold: int = Field(ge=0)
    sales_value_gbp: Decimal = Field(ge=0)


class FulfillmentClassification(_Strict):
    """The output of the analyze_week_fulfillment tool for a single demand line.

    Carries enough provenance for the operator UI to explain the decision:
    the source demand, the resolved ERP sku (if any), the FTP computed
    against compatible warehouses, and the resulting class.
    """

    demand: CanonicalDemandLine
    mapping: MappingResult
    erp_sku: str | None
    """Mirrors mapping.erp_sku for convenience; None when Blocked."""

    ftp_cases: int | None
    """Free-to-promise cases at the iso_week window. None when Blocked
    (cannot compute FTP without a resolved sku)."""

    fill_rate: float | None = None
    """ftp_cases / demand.quantity_cases. None when Blocked or demand=0."""

    classification: FulfillmentClass
    reason: str
    """Human-readable explanation; surfaces in the operator UI as the
    'why was this surfaced?' field."""
