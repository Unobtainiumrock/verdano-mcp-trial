"""End-to-end drift pipeline: forecast CSV + actuals CSV → DriftReport.

Composes Adapter (×2) → Resolver (single mapping over both forecast and
actuals retailer keys) → BaselineCompare. Mirrors the structure of
`analyze_week_fulfillment` so reviewers can read both pipelines as the same
shape.
"""

from __future__ import annotations

from pathlib import Path

from verdano.adapters import Adapter, get_spec
from verdano.canonical import MappingResult, RetailerCode
from verdano.drift import BaselineCompare, DriftReport
from verdano.mapping import MasterIndex, Resolver
from verdano.mapping.priors import DEFAULT_PRIORS, CalibrationPriors
from verdano.pipeline.analyze import ErpSnapshot


def analyze_forecast_plausibility(
    *,
    retailer: RetailerCode,
    iso_week_forecast: str,
    iso_week_actuals: str,
    forecast_csv: str | Path,
    actuals_csv: str | Path,
    erp: ErpSnapshot,
    priors: CalibrationPriors = DEFAULT_PRIORS,
    auto_threshold: float = 0.90,
    threshold_low: float = 0.5,
    threshold_high: float = 1.5,
) -> DriftReport:
    """Run the drift DAG end-to-end for a single (retailer, week-pair) input.

    Stages:
      1. Adapter: forecast CSV → list[RawDemandLine] (week-aggregated if daily).
      2. Adapter: actuals CSV  → list[RawActualsLine].
      3. Resolver: per retailer-key MappingResult.
      4. BaselineCompare: produce DriftReport with per-sku ratios + tally.

    Filtering: forecast lines outside `iso_week_forecast` and actuals lines
    outside `iso_week_actuals` are dropped before resolution to keep the
    mapping universe focused on lines that will actually compare.
    """
    spec = get_spec(retailer)
    adapter = Adapter(spec)

    forecast = [
        f for f in adapter.normalize_forecast(forecast_csv)
        if f.iso_week == iso_week_forecast
    ]
    actuals = [
        a for a in adapter.normalize_actuals(actuals_csv)
        if a.iso_week == iso_week_actuals
    ]

    master = MasterIndex(erp.products)
    resolver = Resolver(master, priors=priors, auto_threshold=auto_threshold)

    # One mapping per unique retailer key seen across forecast + actuals.
    seen: dict[str, MappingResult] = {}
    for fc in forecast:
        key_json = fc.retailer_key.model_dump_json()
        if key_json not in seen:
            seen[key_json] = resolver.resolve(fc.retailer_key)
    for ac in actuals:
        key_json = ac.retailer_key.model_dump_json()
        if key_json not in seen:
            seen[key_json] = resolver.resolve(ac.retailer_key)

    products_by_sku = {p.sku: p for p in erp.products}
    compare = BaselineCompare(
        threshold_low=threshold_low,
        threshold_high=threshold_high,
    )
    return compare.compare(
        forecast_lines=forecast,
        actuals_lines=actuals,
        mappings_by_key=seen,
        products_by_sku=products_by_sku,
        iso_week_forecast=iso_week_forecast,
        iso_week_actuals=iso_week_actuals,
    )
