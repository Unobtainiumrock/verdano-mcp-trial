"""Pluggable drift strategies beyond the built-in plausibility check (D-020).

Each strategy is a plain function ``(DriftContext) -> DriftReport``. New
strategies are added by appending to ``baseline.DEFAULT_STRATEGIES`` at
import time (as this module does for ``residual``). Importing
``verdano.drift`` ensures all built-in strategies are registered.
"""

from __future__ import annotations

from collections import Counter

from verdano.drift.baseline import (
    DEFAULT_STRATEGIES,
    DriftClass,
    DriftContext,
    DriftReport,
    DriftStrategy,
    _index_actuals,
    _resolve_forecast_eaches,
    register_drift_class,
)
from verdano.drift.types import (
    DriftDirection,
    DriftSignal,
    register_drift_direction,
)

# ---------------------------------------------------------------------------
# Register residual-mode directions and drift classes
# ---------------------------------------------------------------------------

for _d in ("over_forecast", "under_forecast", "accurate"):
    register_drift_direction(_d)

for _dc in ("over_forecast", "under_forecast", "accurate"):
    register_drift_class(_dc)


# ---------------------------------------------------------------------------
# residual_strategy: classical signed-residual check
# ---------------------------------------------------------------------------


def residual_strategy(ctx: DriftContext) -> DriftReport:
    """Classical residual drift for same-period forecast vs actuals (D-020).

    residual = actuals_eaches - forecast_eaches  (positive → under-forecast)
    pct_error = residual / max(forecast_eaches, 1)

    Directions:
    - ``over_forecast``: pct_error < -threshold (forecast significantly exceeds actuals)
    - ``under_forecast``: pct_error > threshold (actuals significantly exceed forecast)
    - ``accurate``: abs(pct_error) <= threshold

    Note: unlike ``plausibility_strategy``, promo-flagged lines are **not**
    segmented out. When forecast and actuals share the same period, promo
    uplift has already materialized in actuals, so residual comparison is
    valid regardless of promo state.
    """
    actuals_by_sku = _index_actuals(ctx.actuals_lines, ctx.mappings_by_key)

    signals: list[DriftSignal] = []
    skipped = 0
    threshold = ctx.residual_threshold

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
        residual = actuals_eaches - forecast_eaches
        pct_error = residual / max(forecast_eaches, 1)

        direction: DriftDirection
        reason: str

        if pct_error < -threshold:
            direction = "over_forecast"
            reason = (
                f"forecast {forecast_eaches} eaches exceeds actuals {actuals_eaches} "
                f"by {abs(pct_error):.1%}; residual={residual}"
            )
        elif pct_error > threshold:
            direction = "under_forecast"
            reason = (
                f"actuals {actuals_eaches} exceed forecast {forecast_eaches} "
                f"by {pct_error:.1%}; residual={residual}"
            )
        else:
            direction = "accurate"
            reason = (
                f"pct_error {pct_error:.1%} within ±{threshold:.0%}; "
                f"forecast {forecast_eaches} vs actuals {actuals_eaches}"
            )

        signals.append(DriftSignal(
            mode="residual",
            retailer=fc.retailer,
            iso_week_forecast=ctx.iso_week_forecast,
            iso_week_actuals=ctx.iso_week_actuals,
            erp_sku=mapping.erp_sku,
            retailer_key=fc.retailer_key,
            forecast_eaches=forecast_eaches,
            actuals_eaches=actuals_eaches,
            residual=residual,
            pct_error=pct_error,
            direction=direction,
            promo_flag=fc.promo_flag,
            reason=reason,
        ))

    counts: Counter[str] = Counter(s.direction for s in signals)
    summary: dict[DriftClass, int] = {
        "over_forecast": counts.get("over_forecast", 0),
        "under_forecast": counts.get("under_forecast", 0),
        "accurate": counts.get("accurate", 0),
        "skipped_unmapped": skipped,
    }
    return DriftReport(
        mode="residual",
        iso_week_forecast=ctx.iso_week_forecast,
        iso_week_actuals=ctx.iso_week_actuals,
        summary=summary,
        signals=signals,
    )


# ---------------------------------------------------------------------------
# Register into the default strategy map so DriftAnalyzer discovers it
# ---------------------------------------------------------------------------

DEFAULT_STRATEGIES["residual"] = residual_strategy
