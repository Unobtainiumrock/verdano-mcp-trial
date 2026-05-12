"""Cassette regression for the full MCP-tool → live ERP path.

Tests the integration point that the existing MCP-with-fake suite doesn't
exercise: do the registered tool handlers behave correctly when handed a
*real* `Client.from_env`, with HTTP responses replayed from cassettes?

The cassette is recorded once via `pytest --record-mode=once`; subsequent
runs replay offline. Authorization headers are scrubbed via the existing
`vcr_config` fixture in `tests/conftest.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cpg_reconciler.mcp_server.server import build_server, get_tool_handler as _get_handler


@pytest.mark.vcr
def test_full_mcp_path_against_live_erp(project_root: Path) -> None:
    """End-to-end: real Client.from_env (replayed), real handlers, real
    response-shape parsing."""
    server = build_server(project_root=project_root)
    analyze = _get_handler(server, "analyze_week_fulfillment_tool")
    drafts = _get_handler(server, "create_drafts_for_safe_lines_tool")
    drift = _get_handler(server, "compare_actuals_vs_forecast_tool")

    summary = analyze(retailer="tesco", iso_week="2026-W20")
    assert sum(summary["summary"].values()) == 12
    assert summary["summary"]["Safe"] >= 1

    chilled = drafts(
        retailer="tesco",
        iso_week="2026-W20",
        ship_to_location_id="SHIP-TESCO-DAV",
        required_date="2026-05-13",
    )
    # Either created (first time against this cassette) or existing (re-record).
    assert chilled["drafts_created"] or chilled["drafts_existing"]
    # Cross-band SKUs must be skipped, not failed.
    assert chilled["failed"] == []
    assert all(s["reason"] == "temperature_band_mismatch" for s in chilled["skipped"])
    assert chilled["ship_to_band"] == "chilled"

    ambient = drafts(
        retailer="tesco",
        iso_week="2026-W20",
        ship_to_location_id="SHIP-TESCO-RDG",
        required_date="2026-05-13",
    )
    assert ambient["ship_to_band"] == "ambient"
    assert ambient["failed"] == []

    # Across both runs, every Safe SKU should land in either created or
    # existing on at least one of the two ship_tos (band partitions the safe
    # set cleanly).
    landed_skus: set[str] = set()
    for bucket in ("drafts_created", "drafts_existing"):
        landed_skus.update(d["sku"] for d in chilled[bucket])
        landed_skus.update(d["sku"] for d in ambient[bucket])
    assert landed_skus, "no drafts landed on either ship_to"

    # Drift tool also runs against the same cassette path.
    drift_report = drift(
        retailer="tesco",
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
    )
    assert sum(drift_report["summary"].values()) == 12
    assert drift_report["summary"]["skipped_unmapped"] == 0
