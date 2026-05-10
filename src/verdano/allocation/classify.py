"""Safe / AtRisk / AtRiskSevere / Blocked classification.

Per D-010 + formalism §5.3:

    Safe               if ftp ≥ demand
    AtRisk             if τ_safe ≤ ftp/demand < 1   (auto-allocate per pro-rata)
    AtRiskSevere       if ftp/demand < τ_safe       (human review)
    NeedsVerification  if mapping has a candidate below auto-threshold
    Blocked            if mapping is unresolved (no candidate)

`τ_safe` is config-declared with default 0.90 (D-010, locked as pattern not
constant).
"""

from __future__ import annotations

from verdano.allocation.ftp import FTPCalculator
from verdano.canonical import (
    CanonicalDemandLine,
    FulfillmentClass,
    FulfillmentClassification,
    MappingResult,
)


class Classifier:
    """Apply the fill-rate tripwire to demand + mapping + FTP."""

    def __init__(
        self,
        ftp: FTPCalculator,
        tau_safe: float = 0.90,
    ) -> None:
        self._ftp = ftp
        self._tau_safe = tau_safe

    def classify(
        self,
        demand: CanonicalDemandLine,
        mapping: MappingResult,
        sold_to_customer_id: str | None,
    ) -> FulfillmentClassification:
        # Blocked is upstream of FTP — cannot evaluate without a resolved sku.
        if mapping.state == "Unmapped" or mapping.erp_sku is None:
            return FulfillmentClassification(
                demand=demand,
                mapping=mapping,
                erp_sku=None,
                ftp_cases=None,
                fill_rate=None,
                classification="Blocked",
                reason="no mapping found in cascade (gtin_current..fuzzy_jw)",
            )

        if mapping.state == "NeedsVerification":
            return FulfillmentClassification(
                demand=demand,
                mapping=mapping,
                erp_sku=mapping.erp_sku,
                ftp_cases=None,
                fill_rate=None,
                classification="NeedsVerification",
                reason=(
                    f"mapping needs human verification "
                    f"(stratum={mapping.evidence.stratum if mapping.evidence else '?'}, "
                    f"confidence={mapping.confidence:.2f})"
                ),
            )

        ftp = self._ftp.free_to_promise(
            mapping.erp_sku, demand.iso_week, sold_to_customer_id
        )

        cls: FulfillmentClass
        reason: str
        fill_rate: float | None

        if demand.quantity_cases == 0:
            fill_rate = None
            cls = "Safe"
            reason = "demand is 0; nothing to fulfill"
        else:
            fill_rate = ftp / demand.quantity_cases
            if ftp >= demand.quantity_cases:
                cls = "Safe"
                reason = f"ftp ({ftp}) ≥ demand ({demand.quantity_cases})"
            elif fill_rate >= self._tau_safe:
                cls = "AtRisk"
                reason = (
                    f"fill rate {fill_rate:.2%} ≥ τ_safe {self._tau_safe:.0%}; "
                    f"auto-allocate per pro-rata if op opted in"
                )
            else:
                cls = "AtRiskSevere"
                reason = (
                    f"fill rate {fill_rate:.2%} < τ_safe {self._tau_safe:.0%}; "
                    f"human review required"
                )

        return FulfillmentClassification(
            demand=demand,
            mapping=mapping,
            erp_sku=mapping.erp_sku,
            ftp_cases=ftp,
            fill_rate=fill_rate,
            classification=cls,
            reason=reason,
        )
