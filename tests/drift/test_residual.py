"""Residual drift strategy tests (D-020).

Uses synthetic fixture data to test the classical signed-residual mode
where forecast and actuals share the same ISO week.
"""

from __future__ import annotations

import pytest

from verdano.adapters.raw import RawActualsLine, RawDemandLine
from verdano.pipeline import ErpSnapshot
from verdano.canonical import MappingEvidence, MappingResult, RetailerProductKey
from verdano.drift import DriftAnalyzer, DriftContext, DriftReport
from verdano.drift.strategies import residual_strategy
from verdano.drift.types import _DRIFT_DIRECTION_REGISTRY
from verdano.erp.models import Product
from verdano.pipeline.drift import analyze_drift


# -------------------------------------------------------------------
# Synthetic fixtures
# -------------------------------------------------------------------


def _product(sku: str = "VG-TEST-001", case_pack: int = 1) -> Product:
    return Product(
        sku=sku,
        name="Test Product",
        category="meals",
        case_pack=case_pack,
        temperature_band="ambient",
        current_gtins=["5000000000001"],
        legacy_gtins=[],
        aliases=[],
        status="active",
    )


def _retailer_key(name: str = "Test Product") -> RetailerProductKey:
    return RetailerProductKey(retailer="tesco", name=name)


def _mapping(sku: str = "VG-TEST-001", name: str = "Test Product") -> MappingResult:
    return MappingResult(
        retailer_key=_retailer_key(name),
        state="Resolved",
        erp_sku=sku,
        confidence=0.99,
        evidence=MappingEvidence(
            stratum="exact_gtin",
            matched_value="5000000000001",
            collision_count=1,
        ),
    )


def _forecast_line(
    qty: int = 100, name: str = "Test Product", promo: bool = False,
) -> RawDemandLine:
    return RawDemandLine(
        retailer="tesco",
        iso_week="2026-W20",
        retailer_key=_retailer_key(name),
        raw_quantity=qty,
        raw_unit_mode="eaches",
        location_label="Tesco Daventry",
        promo_flag=promo,
    )


def _actuals_line(
    units: int = 120, name: str = "Test Product",
) -> RawActualsLine:
    return RawActualsLine(
        retailer="tesco",
        iso_week="2026-W20",
        retailer_key=_retailer_key(name),
        segment_label="ambient",
        units_sold=units,
        sales_value_gbp=0,
    )


def _build_context(
    forecast_qty: int = 100,
    actuals_qty: int = 120,
    residual_threshold: float = 0.10,
) -> DriftContext:
    product = _product()
    mapping = _mapping()
    key_json = _retailer_key().model_dump_json()
    return DriftContext(
        forecast_lines=[_forecast_line(qty=forecast_qty)],
        actuals_lines=[_actuals_line(units=actuals_qty)],
        mappings_by_key={key_json: mapping},
        products_by_sku={product.sku: product},
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W20",
        threshold_low=0.5,
        threshold_high=1.5,
        residual_threshold=residual_threshold,
    )


# -------------------------------------------------------------------
# Direction registration
# -------------------------------------------------------------------


def test_residual_directions_registered() -> None:
    for d in ("over_forecast", "under_forecast", "accurate"):
        assert d in _DRIFT_DIRECTION_REGISTRY


# -------------------------------------------------------------------
# Residual strategy — core behavior
# -------------------------------------------------------------------


def test_residual_under_forecast() -> None:
    """Actuals significantly exceed forecast -> under_forecast."""
    ctx = _build_context(forecast_qty=100, actuals_qty=150, residual_threshold=0.10)
    report = residual_strategy(ctx)
    assert report.mode == "residual"
    assert len(report.signals) == 1
    sig = report.signals[0]
    assert sig.direction == "under_forecast"
    assert sig.residual == 50
    assert sig.pct_error == pytest.approx(0.50, abs=0.01)
    assert sig.ratio is None


def test_residual_over_forecast() -> None:
    """Forecast significantly exceeds actuals -> over_forecast."""
    ctx = _build_context(forecast_qty=200, actuals_qty=100, residual_threshold=0.10)
    report = residual_strategy(ctx)
    sig = report.signals[0]
    assert sig.direction == "over_forecast"
    assert sig.residual == -100
    assert sig.pct_error == pytest.approx(-0.50, abs=0.01)


def test_residual_accurate() -> None:
    """Small difference within threshold -> accurate."""
    ctx = _build_context(forecast_qty=100, actuals_qty=105, residual_threshold=0.10)
    report = residual_strategy(ctx)
    sig = report.signals[0]
    assert sig.direction == "accurate"
    assert sig.residual == 5
    assert sig.pct_error == pytest.approx(0.05, abs=0.01)


def test_residual_exact_match() -> None:
    """Exact match -> accurate with zero residual."""
    ctx = _build_context(forecast_qty=100, actuals_qty=100)
    report = residual_strategy(ctx)
    sig = report.signals[0]
    assert sig.direction == "accurate"
    assert sig.residual == 0
    assert sig.pct_error == 0.0


def test_residual_zero_forecast() -> None:
    """Zero forecast uses max(forecast, 1) for pct_error denominator."""
    ctx = _build_context(forecast_qty=0, actuals_qty=50)
    report = residual_strategy(ctx)
    sig = report.signals[0]
    assert sig.direction == "under_forecast"
    assert sig.residual == 50
    assert sig.pct_error == 50.0


def test_residual_skips_unmapped() -> None:
    """Lines without a resolved mapping are counted as skipped."""
    product = _product()
    key_json = _retailer_key().model_dump_json()
    unmapped = MappingResult(
        retailer_key=_retailer_key(),
        state="Blocked",
        erp_sku=None,
        confidence=0.0,
        evidence=None,
    )
    ctx = DriftContext(
        forecast_lines=[_forecast_line()],
        actuals_lines=[_actuals_line()],
        mappings_by_key={key_json: unmapped},
        products_by_sku={product.sku: product},
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W20",
        threshold_low=0.5,
        threshold_high=1.5,
        residual_threshold=0.10,
    )
    report = residual_strategy(ctx)
    assert report.summary["skipped_unmapped"] == 1
    assert len(report.signals) == 0


def test_residual_summary_tally() -> None:
    """Summary correctly tallies all residual directions."""
    product = _product()
    mapping = _mapping()
    key_json = _retailer_key().model_dump_json()
    ctx = DriftContext(
        forecast_lines=[
            _forecast_line(qty=100),
            _forecast_line(qty=100),
            _forecast_line(qty=100),
        ],
        actuals_lines=[_actuals_line(units=100)],
        mappings_by_key={key_json: mapping},
        products_by_sku={product.sku: product},
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W20",
        threshold_low=0.5,
        threshold_high=1.5,
        residual_threshold=0.10,
    )
    report = residual_strategy(ctx)
    total = sum(report.summary.values())
    assert total == len(report.signals) + report.summary.get("skipped_unmapped", 0)


# -------------------------------------------------------------------
# DriftAnalyzer integration with residual
# -------------------------------------------------------------------


def test_drift_analyzer_residual_mode() -> None:
    ctx = _build_context(forecast_qty=100, actuals_qty=80)
    analyzer = DriftAnalyzer()
    report = analyzer.analyze("residual", ctx)
    assert report.mode == "residual"
    assert len(report.signals) == 1
    assert report.signals[0].direction == "over_forecast"


def test_drift_analyzer_custom_strategy() -> None:
    """Custom strategies plug in without modifying defaults."""

    def custom(ctx: DriftContext) -> DriftReport:
        raise NotImplementedError("custom strategy called")

    analyzer = DriftAnalyzer(strategies={"custom": custom})
    assert "custom" in analyzer.available_modes
    with pytest.raises(NotImplementedError, match="custom strategy called"):
        analyzer.analyze("custom", _build_context())


# -------------------------------------------------------------------
# Pipeline integration
# -------------------------------------------------------------------


def test_analyze_drift_plausibility_backward_compat(
    erp_snapshot: ErpSnapshot, project_root: Path,
) -> None:
    """analyze_drift with mode=plausibility matches analyze_forecast_plausibility."""
    from verdano.pipeline import analyze_forecast_plausibility

    legacy = analyze_forecast_plausibility(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    new = analyze_drift(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
        mode="plausibility",
    )
    assert legacy.summary == new.summary
    assert len(legacy.signals) == len(new.signals)
