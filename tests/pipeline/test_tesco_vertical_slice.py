"""End-to-end Tesco vertical slice — fixture-driven, fully offline.

Per BUILD-2-F. Validates that the DAG pipeline (Adapter → Resolver →
case-pack → Classifier) produces the expected classifications on the trial
fixture data, with the gotchas surfacing as designed:

- Legacy-GTIN handling (Berry Smoothie 250ml) — out of scope for Tesco
  fixtures (Tesco rows have no GTINs); see Sainsbury slice.
- Ambiguous-product fixtures (Falafel Bowl 350g vs Large) — surface as
  Resolved at high confidence individually, since each Tesco SKU has its
  own alias in the master.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from verdano.pipeline import ErpSnapshot, analyze_week_fulfillment


def test_tesco_w20_pipeline_produces_classifications(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )

    # Every Tesco line should classify (12 SKUs in the fixture).
    assert len(result.classifications) == 12
    assert sum(result.summary.values()) == 12
    assert result.iso_week == "2026-W20"
    assert result.retailer == "tesco"


def test_tesco_lines_resolve_via_alias_or_better(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Tesco strings have no GTINs, so resolution falls through to E_3 (alias).
    The master has each Tesco-style name as an alias, so all should auto-resolve."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    for c in result.classifications:
        assert c.mapping.state == "Resolved", (
            f"{c.demand.retailer_key.tesco_item} did not auto-resolve: "
            f"{c.mapping.state} via {c.mapping.evidence}"
        )
        assert c.mapping.evidence is not None
        assert c.mapping.evidence.stratum == "E3"
        assert c.mapping.confidence >= 0.95


def test_tesco_falafel_bowl_pair_maps_to_distinct_skus(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """The Tesco fixture has T-9302 (Falafel Bowl 350g) and T-9303 (Falafel Bowl Large).
    Each Tesco-side string is unique enough to alias a different ERP SKU,
    so they should map to *different* SKUs (not collapse)."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    by_item = {
        c.demand.retailer_key.tesco_item: c.erp_sku for c in result.classifications
    }
    assert by_item["T-9302"] != by_item["T-9303"], (
        "Falafel Bowl 350g and Falafel Bowl Large must not collapse onto the same SKU"
    )


def test_tesco_classifications_explain_themselves(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Every classification should carry a non-empty operator-readable reason."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    for c in result.classifications:
        assert c.reason, f"{c.demand.retailer_key.tesco_item}: empty reason"


def test_tesco_safe_lines_have_ftp_at_least_demand(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    for c in result.classifications:
        if c.classification == "Safe":
            assert c.ftp_cases is not None
            assert c.ftp_cases >= c.demand.quantity_cases, (
                f"{c.demand.retailer_key.tesco_item}: Safe but ftp={c.ftp_cases} "
                f"< demand={c.demand.quantity_cases}"
            )


def test_pipeline_is_deterministic(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Per formalism §6.2, DAG nodes are pure. Two runs over the same
    inputs must produce identical outputs."""
    a = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    b = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    assert a.summary == b.summary
    assert [c.model_dump() for c in a.classifications] == [
        c.model_dump() for c in b.classifications
    ]


@pytest.mark.parametrize("iso_week", ["2026-W19", "2026-W21", "9999-W01"])
def test_pipeline_returns_empty_on_other_weeks(
    erp_snapshot: ErpSnapshot, project_root: Path, iso_week: str
) -> None:
    """Filtering to a non-W20 ISO week should produce zero classifications."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "tesco_forecast_week20.csv",
        retailer="tesco",
        iso_week=iso_week,
        erp=erp_snapshot,
    )
    assert sum(result.summary.values()) == 0
    assert result.classifications == []
