"""End-to-end drift pipeline: forecast CSV + actuals CSV -> DriftReport.

Composes Adapter (x2) -> Resolver (single mapping over both forecast and
actuals retailer keys) -> DriftAnalyzer. Mirrors the structure of
``analyze_week_fulfillment`` so reviewers can read both pipelines as the
same shape.

Supports multiple drift modes (D-020, D-024):
- ``plausibility``: lagged-actuals ratio check (default, D-012)
- ``residual``: classical signed-residual for same-period comparison
- ``markov``: regime-detection via transition-matrix analysis (D-024)
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from pathlib import Path

from cpg_reconciler.adapters import Adapter, get_spec
from cpg_reconciler.canonical import MappingResult, RetailerCode
from cpg_reconciler.drift import DriftAnalyzer, DriftContext, DriftReport
from cpg_reconciler.drift.markov import MarkovDriftContext
from cpg_reconciler.mapping import MasterIndex, Resolver
from cpg_reconciler.mapping.normalize import NormalizationPipeline
from cpg_reconciler.mapping.priors import DEFAULT_PRIORS, CalibrationPriors
from cpg_reconciler.pipeline.analyze import ErpSnapshot
from cpg_reconciler.storage.repository import Repository, ResidualRecord


def _load_residual_history(
    repository: Repository | None,
    skus: set[str],
    max_weeks: int,
) -> dict[str, list[ResidualRecord]]:
    """Load bounded residual history from the repository for each SKU."""
    if repository is None:
        return {}
    history: dict[str, list[ResidualRecord]] = {}
    for sku in skus:
        records = repository.get_residual_history(sku, max_weeks=max_weeks)
        if records:
            history[sku] = records
    return history


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
    normalizer: NormalizationPipeline | None = None,
    repository: Repository | None = None,
    markov_min_weeks: int = 4,
    markov_persistence_threshold: int = 3,
    markov_max_weeks: int = 52,
    markov_kl_threshold: float = 0.5,
) -> DriftReport:
    """Run the drift DAG end-to-end for a single (retailer, week-pair) input.

    Parameters
    ----------
    mode : str
        ``"plausibility"`` (default) for lagged-actuals ratio check.
        ``"residual"`` for classical signed-residual (same-period only).
        ``"markov"`` for Markov regime-detection (D-024).
    repository : Repository | None
        Required for ``mode="markov"`` to load residual history.
        Also used after ``mode="residual"`` to persist new residuals.

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

    master = MasterIndex(erp.products, normalizer=normalizer)
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

    base_ctx = DriftContext(
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

    ctx: DriftContext
    if mode == "markov":
        resolved_skus = {
            m.erp_sku
            for m in seen.values()
            if m.state == "Resolved" and m.erp_sku is not None
        }
        history = _load_residual_history(
            repository, resolved_skus, max_weeks=markov_max_weeks
        )
        ctx = MarkovDriftContext(
            **{f.name: getattr(base_ctx, f.name) for f in dc_fields(base_ctx)},
            residual_history=history,
            min_weeks=markov_min_weeks,
            persistence_threshold=markov_persistence_threshold,
            max_history_weeks=markov_max_weeks,
            kl_divergence_threshold=markov_kl_threshold,
        )
    else:
        ctx = base_ctx

    analyzer = DriftAnalyzer()
    report = analyzer.analyze(mode, ctx)

    if mode == "residual" and repository is not None:
        for sig in report.signals:
            if sig.direction in ("high", "low", "ok"):
                direction_map = {"high": "under_forecast", "low": "over_forecast", "ok": "accurate"}
                record = ResidualRecord(
                    erp_sku=sig.erp_sku,
                    iso_week=sig.iso_week_actuals,
                    direction=direction_map.get(sig.direction, sig.direction),
                    pct_error=sig.pct_error or 0.0,
                )
                repository.save_residual_history(record)

    return report


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
