"""Baseline comparison: lagged actuals vs forecast in eaches.

Implements the threshold-flagging logic for the trial-scope drift signal
(D-012). The class is stateless given its construction-time thresholds; it's
just a function-with-config wearing class clothing for ergonomic reuse.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from verdano.adapters.raw import RawActualsLine, RawDemandLine
from verdano.canonical import MappingResult
from verdano.drift.types import DriftDirection, DriftSignal
from verdano.erp.models import Product

DriftClass = str
_DRIFT_CLASS_REGISTRY: set[str] = set()


def register_drift_class(cls: str) -> None:
    _DRIFT_CLASS_REGISTRY.add(cls)


for _dc in ("high", "low", "ok", "skipped_unmapped"):
    register_drift_class(_dc)


class DriftReport(BaseModel):
    """Aggregated drift output: per-signal records plus a small tally."""

    model_config = ConfigDict(frozen=True)

    iso_week_forecast: str
    iso_week_actuals: str
    summary: dict[DriftClass, int] = Field(
        description="Tally — counts of high / low / ok / skipped_unmapped."
    )
    signals: list[DriftSignal]


class BaselineCompare:
    """Compare a Resolved forecast against lagged actuals.

    Forecasts that fail mapping (Blocked / NeedsVerification) are *not* turned
    into signals — they're counted under `summary["skipped_unmapped"]` so the
    operator sees the volume of un-comparable lines without polluting the
    signal stream.
    """

    def __init__(
        self,
        threshold_low: float = 0.5,
        threshold_high: float = 1.5,
    ) -> None:
        if not 0.0 < threshold_low < 1.0 < threshold_high:
            raise ValueError("require 0 < threshold_low < 1 < threshold_high")
        self._lo = threshold_low
        self._hi = threshold_high

    def compare(
        self,
        forecast_lines: list[RawDemandLine],
        actuals_lines: list[RawActualsLine],
        mappings_by_key: dict[str, MappingResult],
        products_by_sku: dict[str, Product],
        iso_week_forecast: str,
        iso_week_actuals: str,
    ) -> DriftReport:
        """Produce a `DriftReport` over the supplied raw lines + mappings.

        `mappings_by_key` is keyed by `RetailerProductKey.model_dump_json()` —
        the canonical hash key the pipeline uses elsewhere.
        """
        # Index actuals by resolved erp_sku (after mapping). Multiple actuals
        # rows may share the same sku across segments; we sum eaches.
        actuals_eaches_by_sku: Counter[str] = Counter()
        for actual in actuals_lines:
            mapping = mappings_by_key.get(actual.retailer_key.model_dump_json())
            if mapping and mapping.state == "Resolved" and mapping.erp_sku:
                actuals_eaches_by_sku[mapping.erp_sku] += actual.units_sold

        signals: list[DriftSignal] = []
        skipped = 0
        for fc in forecast_lines:
            mapping = mappings_by_key.get(fc.retailer_key.model_dump_json())
            if mapping is None or mapping.state != "Resolved" or mapping.erp_sku is None:
                skipped += 1
                continue

            product = products_by_sku.get(mapping.erp_sku)
            if product is None:
                skipped += 1
                continue

            forecast_eaches = (
                fc.raw_quantity * product.case_pack
                if fc.raw_unit_mode == "cases"
                else fc.raw_quantity
            )
            actuals_eaches = actuals_eaches_by_sku.get(mapping.erp_sku, 0)
            denominator = max(actuals_eaches, 1)
            ratio = forecast_eaches / denominator

            direction: DriftDirection
            promo_segmented = False
            reason: str

            if fc.promo_flag:
                # Promo periods produce expected uplift — exclude from
                # baseline comparison rather than flag.
                direction = "ok"
                promo_segmented = True
                reason = (
                    f"promo period (forecast row promo_flag=True); "
                    f"excluded from baseline check. ratio={ratio:.2f}"
                )
            elif actuals_eaches == 0:
                # No lagged baseline at all. We can't comment on plausibility;
                # the ratio is degenerate. Flag as `ok` with a known-unknown.
                direction = "ok"
                reason = (
                    f"no {iso_week_actuals} actuals for sku {mapping.erp_sku}; "
                    f"baseline check inapplicable"
                )
            elif ratio < self._lo:
                direction = "low"
                reason = (
                    f"forecast {forecast_eaches} eaches is {ratio:.2f}× lagged "
                    f"actuals {actuals_eaches}; below low threshold {self._lo}"
                )
            elif ratio > self._hi:
                direction = "high"
                reason = (
                    f"forecast {forecast_eaches} eaches is {ratio:.2f}× lagged "
                    f"actuals {actuals_eaches}; above high threshold {self._hi}"
                )
            else:
                direction = "ok"
                reason = (
                    f"ratio {ratio:.2f} within [{self._lo}, {self._hi}]; "
                    f"forecast plausible vs lagged actuals"
                )

            signals.append(DriftSignal(
                retailer=fc.retailer,
                iso_week_forecast=iso_week_forecast,
                iso_week_actuals=iso_week_actuals,
                erp_sku=mapping.erp_sku,
                retailer_key=fc.retailer_key,
                forecast_eaches=forecast_eaches,
                actuals_eaches=actuals_eaches,
                ratio=ratio,
                direction=direction,
                promo_flag=fc.promo_flag,
                promo_segmented=promo_segmented,
                reason=reason,
            ))

        counts: Counter[str] = Counter(s.direction for s in signals)
        summary: dict[DriftClass, int] = {
            "high": counts.get("high", 0),
            "low": counts.get("low", 0),
            "ok": counts.get("ok", 0),
            "skipped_unmapped": skipped,
        }
        return DriftReport(
            iso_week_forecast=iso_week_forecast,
            iso_week_actuals=iso_week_actuals,
            summary=summary,
            signals=signals,
        )
