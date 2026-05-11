"""End-to-end drift pipeline: forecast CSV + actuals CSV -> DriftReport.

Composes Adapter (x2) -> Resolver (single mapping over both forecast and
actuals retailer keys) -> DriftAnalyzer. Mirrors the structure of
``analyze_week_fulfillment`` so reviewers can read both pipelines as the
same shape.

Supports multiple drift modes (D-020):
- ``plausibility``: lagged-actuals ratio check (default, D-012)
- ``residual``: classical signed-residual for same-period comparison
"""

from __future__ import annotations

from pathlib import Path

from verdano.adapters import Adapter, get_spec
from verdano.canonical import MappingResult, RetailerCode
from verdano.drift import DriftAnalyzer, DriftContext, DriftReport
from verdano.mapping import MasterIndex, Resolver
from verdano.mapping.priors import DEFAULT_PRIORS, CalibrationPriors
from verdano.pipeline.analyze import ErpSnapshot


def analyze_drift(
    *,
    retailer: RetailerCode,
    iso_week_forecast: str,
    iso_week_actuals: str,
    forecast_csv: str | Path,
    actuals_csv: str | Path,
    erp: ErpSnapshot,
    mode: str = "plausibility",
    priors: CalibrationPriors = DEFAULT_PRIORS,
    auto_threshold: float = 0.90,
    threshold_low: float = 0.5,
    threshold_high: float = 1.5,
    residual_threshold: float = 0.10,
) -> DriftReport:
    """Run the drift DAG end-to-end for a single (retailer, week-pair) input.

    Parameters
    ----------
    mode : str
        ``"plausibility"`` (default) for lagged-actuals ratio check.
        ``"residual"`` for classical signed-residual (same-period only).

    Raises
    ------
    ValueError
        If ``mode="residual"`` but the forecast and actuals weeks differ.

    Stages:
      1. Adapter: forecast CSV -> list[RawDemandLine] (week-aggregated if daily).
      2. Adapter: actuals CSV  -> list[RawActualsLine].
      3. Resolver: per retailer-key MappingResult.
      4. DriftAnalyzer: dispatch to the selected strategy and produce DriftReport.
    """
    if mode == "residual" and iso_week_forecast != iso_week_actuals:
        raise ValueError(
            f"residual mode requires forecast and actuals from the same "
            f"period; got forecast={iso_week_forecast}, actuals={iso_week_actuals}"
        )

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

    ctx = DriftContext(
        forecast_lines=forecast,
        actuals_lines=actuals,
        mappings_by_key=seen,
        products_by_sku=products_by_sku,
        iso_week_forecast=iso_week_forecast,
        iso_week_actuals=iso_week_actuals,
        threshold_low=threshold_low,
        threshold_high=threshold_high,
        residual_threshold=residual_threshold,
    )
    analyzer = DriftAnalyzer()
    return analyzer.analyze(mode, ctx)


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
    """Backward-compatible alias for ``analyze_drift(mode="plausibility")``.

    Preserves the original D-012 signature so existing callers (tests, MCP
    tool) continue to work without changes.
    """
    return analyze_drift(
        retailer=retailer,
        iso_week_forecast=iso_week_forecast,
        iso_week_actuals=iso_week_actuals,
        forecast_csv=forecast_csv,
        actuals_csv=actuals_csv,
        erp=erp,
        mode="plausibility",
        priors=priors,
        auto_threshold=auto_threshold,
        threshold_low=threshold_low,
        threshold_high=threshold_high,
    )
