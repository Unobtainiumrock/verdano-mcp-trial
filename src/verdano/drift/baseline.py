"""Drift analysis framework (D-012, D-020).

Provides a strategy-based drift analyzer that dispatches to pluggable
strategy functions. The built-in ``plausibility`` strategy implements the
lagged-actuals ratio check from D-012. Additional strategies (``residual``,
future Markov) register without modifying this file.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from verdano.adapters.raw import RawActualsLine, RawDemandLine
from verdano.canonical import MappingResult
from verdano.drift.types import DriftDirection, DriftSignal
from verdano.erp.models import Product

# ---------------------------------------------------------------------------
# DriftClass registry (unchanged from pre-refactor)
# ---------------------------------------------------------------------------

DriftClass = str
_DRIFT_CLASS_REGISTRY: set[str] = set()


def register_drift_class(cls: str) -> None:
    _DRIFT_CLASS_REGISTRY.add(cls)


def known_drift_classes() -> frozenset[str]:
    return frozenset(_DRIFT_CLASS_REGISTRY)


for _dc in ("high", "low", "ok", "skipped_unmapped"):
    register_drift_class(_dc)


# ---------------------------------------------------------------------------
# DriftReport (unchanged)
# ---------------------------------------------------------------------------


class DriftReport(BaseModel):
    """Aggregated drift output: per-signal records plus a small tally."""

    model_config = ConfigDict(frozen=True)

    mode: str = "plausibility"
    iso_week_forecast: str
    iso_week_actuals: str
    summary: dict[DriftClass, int] = Field(
        description="Tally of direction counts plus skipped_unmapped."
    )
    signals: list[DriftSignal]


# ---------------------------------------------------------------------------
# DriftContext — shared inputs consumed by every strategy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftContext:
    """Immutable bag of inputs for a drift strategy function."""

    forecast_lines: list[RawDemandLine]
    actuals_lines: list[RawActualsLine]
    mappings_by_key: dict[str, MappingResult]
    products_by_sku: dict[str, Product]
    iso_week_forecast: str
    iso_week_actuals: str
    threshold_low: float
    threshold_high: float
    residual_threshold: float


# ---------------------------------------------------------------------------
# DriftStrategy callable type
# ---------------------------------------------------------------------------

DriftStrategy = Callable[[DriftContext], DriftReport]
"""A drift strategy receives a ``DriftContext`` and returns a ``DriftReport``."""


# ---------------------------------------------------------------------------
# Built-in strategy: plausibility (D-012)
# ---------------------------------------------------------------------------


def _index_actuals(
    actuals: list[RawActualsLine],
    mappings: dict[str, MappingResult],
) -> Counter[str]:
    """Sum actuals eaches by resolved ERP SKU."""
    by_sku: Counter[str] = Counter()
    for actual in actuals:
        mapping = mappings.get(actual.retailer_key.model_dump_json())
        if mapping and mapping.state == "Resolved" and mapping.erp_sku:
            by_sku[mapping.erp_sku] += actual.units_sold
    return by_sku


def _resolve_forecast_eaches(
    fc: RawDemandLine, product: Product
) -> int:
    """Convert forecast quantity to eaches using case_pack if needed."""
    if fc.raw_unit_mode == "cases":
        return fc.raw_quantity * product.case_pack
    return fc.raw_quantity


def plausibility_strategy(ctx: DriftContext) -> DriftReport:
    """Lagged-actuals ratio check (D-012).

    ratio = forecast_eaches / max(actuals_eaches, 1)
    """
    actuals_by_sku = _index_actuals(ctx.actuals_lines, ctx.mappings_by_key)

    signals: list[DriftSignal] = []
    skipped = 0

    for fc in ctx.forecast_lines:
        mapping = ctx.mappings_by_key.get(fc.retailer_key.model_dump_json())
        if mapping is None or mapping.state != "Resolved" or mapping.erp_sku is None:
            skipped += 1
            continue

        product = ctx.products_by_sku.get(mapping.erp_sku)
        if product is None:
            skipped += 1
            continue

        forecast_eaches = _resolve_forecast_eaches(fc, product)
        actuals_eaches = actuals_by_sku.get(mapping.erp_sku, 0)
        denominator = max(actuals_eaches, 1)
        ratio = forecast_eaches / denominator

        direction: DriftDirection
        promo_segmented = False
        reason: str

        if fc.promo_flag:
            direction = "ok"
            promo_segmented = True
            reason = (
                f"promo period (forecast row promo_flag=True); "
                f"excluded from baseline check. ratio={ratio:.2f}"
            )
        elif actuals_eaches == 0:
            direction = "ok"
            reason = (
                f"no {ctx.iso_week_actuals} actuals for sku {mapping.erp_sku}; "
                f"baseline check inapplicable"
            )
        elif ratio < ctx.threshold_low:
            direction = "low"
            reason = (
                f"forecast {forecast_eaches} eaches is {ratio:.2f}× lagged "
                f"actuals {actuals_eaches}; below low threshold {ctx.threshold_low}"
            )
        elif ratio > ctx.threshold_high:
            direction = "high"
            reason = (
                f"forecast {forecast_eaches} eaches is {ratio:.2f}× lagged "
                f"actuals {actuals_eaches}; above high threshold {ctx.threshold_high}"
            )
        else:
            direction = "ok"
            reason = (
                f"ratio {ratio:.2f} within [{ctx.threshold_low}, {ctx.threshold_high}]; "
                f"forecast plausible vs lagged actuals"
            )

        signals.append(DriftSignal(
            mode="plausibility",
            retailer=fc.retailer,
            iso_week_forecast=ctx.iso_week_forecast,
            iso_week_actuals=ctx.iso_week_actuals,
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
        mode="plausibility",
        iso_week_forecast=ctx.iso_week_forecast,
        iso_week_actuals=ctx.iso_week_actuals,
        summary=summary,
        signals=signals,
    )


# ---------------------------------------------------------------------------
# Strategy registry + DriftAnalyzer dispatcher
# ---------------------------------------------------------------------------

DEFAULT_STRATEGIES: dict[str, DriftStrategy] = {
    "plausibility": plausibility_strategy,
}


class DriftAnalyzer:
    """Dispatches to pluggable drift strategy functions by mode name.

    New strategies are registered by adding to ``DEFAULT_STRATEGIES`` or
    passing a custom dict at construction time.
    """

    def __init__(
        self, strategies: dict[str, DriftStrategy] | None = None
    ) -> None:
        self._strategies = strategies if strategies is not None else dict(DEFAULT_STRATEGIES)

    @property
    def available_modes(self) -> list[str]:
        return sorted(self._strategies)

    def analyze(self, mode: str, ctx: DriftContext) -> DriftReport:
        strategy = self._strategies.get(mode)
        if strategy is None:
            raise ValueError(
                f"unknown drift mode {mode!r}; available: {self.available_modes}"
            )
        return strategy(ctx)


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------


class BaselineCompare:
    """Legacy wrapper — delegates to ``DriftAnalyzer`` with plausibility mode.

    Preserved for backward compatibility with existing callers and tests.
    New code should use ``DriftAnalyzer`` directly.
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
        self._analyzer = DriftAnalyzer()

    def compare(
        self,
        forecast_lines: list[RawDemandLine],
        actuals_lines: list[RawActualsLine],
        mappings_by_key: dict[str, MappingResult],
        products_by_sku: dict[str, Product],
        iso_week_forecast: str,
        iso_week_actuals: str,
    ) -> DriftReport:
        ctx = DriftContext(
            forecast_lines=forecast_lines,
            actuals_lines=actuals_lines,
            mappings_by_key=mappings_by_key,
            products_by_sku=products_by_sku,
            iso_week_forecast=iso_week_forecast,
            iso_week_actuals=iso_week_actuals,
            threshold_low=self._lo,
            threshold_high=self._hi,
            residual_threshold=0.10,
        )
        return self._analyzer.analyze("plausibility", ctx)
