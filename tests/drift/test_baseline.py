"""Drift module tests — plausibility mode (lagged-actuals ratio check).

Per D-012, the drift signal is `forecast_eaches / max(actuals_eaches, 1)`,
threshold-flagged into high/low/ok with promo segmentation. These tests
exercise the framing on real Tesco/Sainsbury fixture data and verify the
D-020 backward-compatible refactoring.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from verdano.drift import (
    DriftAnalyzer,
    DriftContext,
    plausibility_strategy,
)
from verdano.drift.baseline import DriftReport
from verdano.drift.types import (
    DriftSignal,
    _DRIFT_DIRECTION_REGISTRY,
    known_drift_directions,
    register_drift_direction,
)
from verdano.mcp_server.server import build_server, get_tool_handler
from verdano.pipeline import (
    ErpSnapshot,
    analyze_forecast_plausibility,
)


# -------------------------------------------------------------------
# Plausibility pipeline tests (unchanged assertions, backward compat)
# -------------------------------------------------------------------


def test_tesco_drift_pipeline_runs(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    report = analyze_forecast_plausibility(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    assert report.summary["skipped_unmapped"] == 0
    assert sum(report.summary.values()) == 12
    assert report.iso_week_forecast == "2026-W20"
    assert report.iso_week_actuals == "2026-W19"
    assert report.mode == "plausibility"


def test_tesco_promo_lines_are_segmented(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """T-9103 (Thai Green — promo bay) and T-9401 (Green Smoothie — fixture
    expansion) carry promo_flag=True; both must be `direction=ok` AND
    promo_segmented=True regardless of ratio."""
    report = analyze_forecast_plausibility(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    promo_signals = [s for s in report.signals if s.promo_segmented]
    assert len(promo_signals) >= 2
    for s in promo_signals:
        assert s.promo_flag is True
        assert s.direction == "ok"
        assert "promo period" in s.reason.lower()


def test_tesco_thresholding_finds_at_least_one_high(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """The fixture has VG-MUSH-500 with forecast=176 vs lagged=104 -> ratio~1.69,
    above the default 1.5 threshold. At least one `high` signal expected."""
    report = analyze_forecast_plausibility(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    assert report.summary["high"] >= 1


def test_sainsburys_drift_skips_unresolved(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Berry Smoothie (legacy GTIN, NeedsVerification) and the no-GTIN
    Falafel Bowl (fuzzy_jw at NeedsVerification) must NOT show up in the
    signal stream — they're counted under skipped_unmapped instead."""
    report = analyze_forecast_plausibility(
        retailer="sainsburys",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        actuals_csv=project_root / "data" / "sainsburys_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    assert report.summary["skipped_unmapped"] >= 2
    surfaced_skus = {s.erp_sku for s in report.signals}
    assert "VG-BRSM-250" not in surfaced_skus


def test_sainsburys_promo_asymmetry(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Sainsbury's CSV has no promo column; every signal must have
    promo_flag=False and promo_segmented=False."""
    report = analyze_forecast_plausibility(
        retailer="sainsburys",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        actuals_csv=project_root / "data" / "sainsburys_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    for s in report.signals:
        assert s.promo_flag is False
        assert s.promo_segmented is False


def test_drift_pipeline_is_deterministic(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    a = analyze_forecast_plausibility(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    b = analyze_forecast_plausibility(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        forecast_csv=project_root / "data" / "tesco_forecast_week20.csv",
        actuals_csv=project_root / "data" / "tesco_epos_actuals_week19.csv",
        erp=erp_snapshot,
    )
    assert a.summary == b.summary
    assert a.model_dump() == b.model_dump()


# -------------------------------------------------------------------
# MCP tool wiring
# -------------------------------------------------------------------


@pytest.fixture()
def fake_client_factory(erp_snapshot: ErpSnapshot) -> Any:
    @contextmanager
    def factory():  # type: ignore[no-untyped-def]
        client = MagicMock()
        client.list_products.return_value = erp_snapshot.products
        client.list_customers.return_value = erp_snapshot.customers
        client.list_warehouses.return_value = erp_snapshot.warehouses
        client.list_inventory.return_value = erp_snapshot.inventory
        client.list_open_orders.return_value = erp_snapshot.open_orders
        yield client
    return factory


def test_drift_mcp_tool_wiring(project_root: Path, fake_client_factory: Any) -> None:
    """The compare_actuals_vs_forecast_tool returns a structured DriftReport
    via the FastMCP-registered handler against a faked client."""
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = get_tool_handler(server, "compare_actuals_vs_forecast_tool")
    result = handler(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
    )
    assert "summary" in result
    assert "signals" in result
    assert result["mode"] == "plausibility"
    assert sum(result["summary"].values()) == 12


def test_drift_mcp_tool_residual_week_mismatch(
    project_root: Path, fake_client_factory: Any,
) -> None:
    """Residual mode with differing weeks must return a validation error."""
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = get_tool_handler(server, "compare_actuals_vs_forecast_tool")
    result = handler(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        mode="residual",
    )
    assert "error" in result
    assert "same period" in result["error"]


# -------------------------------------------------------------------
# DriftDirection registry extensibility
# -------------------------------------------------------------------


def test_drift_direction_registry_has_baseline_directions() -> None:
    dirs = known_drift_directions()
    assert {"high", "low", "ok"}.issubset(dirs)


def test_drift_direction_registry_is_extensible() -> None:
    register_drift_direction("test_custom_direction")
    assert "test_custom_direction" in _DRIFT_DIRECTION_REGISTRY
    _DRIFT_DIRECTION_REGISTRY.discard("test_custom_direction")


# -------------------------------------------------------------------
# DriftSignal carries mode-specific fields
# -------------------------------------------------------------------


def _test_retailer_key() -> dict[str, str]:
    return {"retailer": "tesco", "name": "Test Product"}


def test_drift_signal_plausibility_fields() -> None:
    sig = DriftSignal(
        mode="plausibility",
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        erp_sku="VG-TEST-001",
        retailer_key=_test_retailer_key(),
        forecast_eaches=100,
        actuals_eaches=80,
        ratio=1.25,
        direction="ok",
        reason="test",
    )
    assert sig.ratio == 1.25
    assert sig.residual is None
    assert sig.pct_error is None


def test_drift_signal_residual_fields() -> None:
    sig = DriftSignal(
        mode="residual",
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W20",
        erp_sku="VG-TEST-001",
        retailer_key=_test_retailer_key(),
        forecast_eaches=100,
        actuals_eaches=120,
        residual=20,
        pct_error=0.20,
        direction="under_forecast",
        reason="test",
    )
    assert sig.residual == 20
    assert sig.pct_error == 0.20
    assert sig.ratio is None


# -------------------------------------------------------------------
# DriftAnalyzer dispatches correctly
# -------------------------------------------------------------------


def test_drift_analyzer_unknown_mode_raises() -> None:
    analyzer = DriftAnalyzer()
    ctx = DriftContext(
        forecast_lines=[],
        actuals_lines=[],
        mappings_by_key={},
        products_by_sku={},
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        threshold_low=0.5,
        threshold_high=1.5,
        residual_threshold=0.10,
    )
    with pytest.raises(ValueError, match="unknown drift mode"):
        analyzer.analyze("nonexistent_mode", ctx)


def test_drift_analyzer_available_modes() -> None:
    analyzer = DriftAnalyzer()
    modes = analyzer.available_modes
    assert "plausibility" in modes
    assert "residual" in modes


def test_drift_analyzer_plausibility_with_empty_context() -> None:
    """Plausibility strategy on empty inputs produces an empty report."""
    analyzer = DriftAnalyzer()
    ctx = DriftContext(
        forecast_lines=[],
        actuals_lines=[],
        mappings_by_key={},
        products_by_sku={},
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        threshold_low=0.5,
        threshold_high=1.5,
        residual_threshold=0.10,
    )
    report = analyzer.analyze("plausibility", ctx)
    assert report.mode == "plausibility"
    assert report.signals == []
    assert report.summary["skipped_unmapped"] == 0
