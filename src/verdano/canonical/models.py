"""Canonical entity contracts.

The morphism domains/codomains from formalism §2. These are the *single*
representation that downstream pipeline stages consume — adapter outputs
must conform to these regardless of retailer source shape.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# RetailerCode: runtime-extensible retailer identifier (D-015)
# ---------------------------------------------------------------------------
# Previously a Literal["tesco", "sainsburys"]. Now a plain str alias with a
# runtime registry so that adding a retailer requires only a new spec
# instance — no type-definition edits. Validation happens at spec registration
# and at tool-call boundaries, not at the type level.
# ---------------------------------------------------------------------------

RetailerCode = str
"""Runtime-extensible retailer identifier.

Validated against the adapter-spec registry at runtime rather than via a
closed Literal. See D-015 and `adapters/spec.py:register_retailer`."""

_RETAILER_REGISTRY: set[str] = set()


def register_retailer_code(code: str) -> None:
    """Register a retailer code as valid. Called by `adapters/spec.py`."""
    _RETAILER_REGISTRY.add(code)


def known_retailer_codes() -> frozenset[str]:
    """Return the set of currently registered retailer codes."""
    return frozenset(_RETAILER_REGISTRY)


def validate_retailer_code(code: str) -> str:
    """Raise ValueError if ``code`` is not a registered retailer."""
    if code not in _RETAILER_REGISTRY:
        raise ValueError(
            f"unknown retailer code {code!r}; "
            f"registered: {sorted(_RETAILER_REGISTRY)}"
        )
    return code


# ---------------------------------------------------------------------------
# Stratum: runtime-extensible cascade strata
# ---------------------------------------------------------------------------

Stratum = str
"""Runtime-extensible stratum identifier for the cascade resolver."""

_STRATUM_REGISTRY: list[str] = []


def register_stratum(name: str, *, after: str | None = None) -> None:
    """Register a cascade stratum. Order matters (cascade priority)."""
    if name in _STRATUM_REGISTRY:
        return
    if after is not None and after in _STRATUM_REGISTRY:
        idx = _STRATUM_REGISTRY.index(after) + 1
        _STRATUM_REGISTRY.insert(idx, name)
    else:
        _STRATUM_REGISTRY.append(name)


def known_strata() -> list[str]:
    """Return the ordered list of registered strata."""
    return list(_STRATUM_REGISTRY)


for _s in ("gtin_current", "gtin_legacy", "alias_exact", "tfidf_overlap", "fuzzy_jw"):
    register_stratum(_s)


# ---------------------------------------------------------------------------
# MappingState: runtime-extensible review states
# ---------------------------------------------------------------------------

MappingState = str
"""Runtime-extensible mapping review state."""

_MAPPING_STATE_REGISTRY: set[str] = set()


def register_mapping_state(state: str) -> None:
    _MAPPING_STATE_REGISTRY.add(state)


def known_mapping_states() -> frozenset[str]:
    return frozenset(_MAPPING_STATE_REGISTRY)


for _ms in ("Resolved", "NeedsVerification", "Unmapped"):
    register_mapping_state(_ms)


# ---------------------------------------------------------------------------
# FulfillmentClass: runtime-extensible classification tiers
# ---------------------------------------------------------------------------

FulfillmentClass = str
"""Runtime-extensible fulfillment classification tier."""

_FULFILLMENT_CLASS_REGISTRY: set[str] = set()


def register_fulfillment_class(cls: str) -> None:
    _FULFILLMENT_CLASS_REGISTRY.add(cls)


def known_fulfillment_classes() -> frozenset[str]:
    return frozenset(_FULFILLMENT_CLASS_REGISTRY)


for _fc in ("Safe", "AtRisk", "AtRiskSevere", "NeedsVerification", "Blocked"):
    register_fulfillment_class(_fc)


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
