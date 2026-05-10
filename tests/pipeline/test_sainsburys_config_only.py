"""Sainsbury's via config-only — validates the D-001 abstraction.

The contract: onboarding Sainsbury's required *no new Python*. Only the
`SAINSBURYS_SPEC` instance in `src/verdano/adapters/spec.py` (declarative
column mapping + unit/time mode + DOW kernel). Same Adapter, same Resolver,
same FTP, same Classifier.

These tests assert the abstraction holds and that the Sainsbury-specific
fixture gotchas (legacy GTIN; no-GTIN/no-size ambiguous Falafel Bowl) route
correctly.
"""

from __future__ import annotations

from pathlib import Path

from verdano.pipeline import ErpSnapshot, analyze_week_fulfillment


def test_sainsburys_w20_pipeline_runs(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """The Sainsbury's spec is declarative; the same pipeline must run on it."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        retailer="sainsburys",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    assert len(result.classifications) == 12
    assert result.retailer == "sainsburys"


def test_sainsburys_gtin_rows_resolve_via_e1(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Rows with current_gtins should fire the E_1 stratum at ≥0.95 confidence."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        retailer="sainsburys",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    e1_rows = [
        c for c in result.classifications
        if c.mapping.evidence is not None and c.mapping.evidence.stratum == "gtin_current"
    ]
    # 12 fixture rows total; 2 have blank GTIN (Tom Basil, Falafel Bowl) and
    # 1 (Berry Smoothie 5060000099999) is on legacy_gtins so fires E2 not E1.
    # Net: 9 rows resolve via E1.
    assert len(e1_rows) == 9
    assert all(c.mapping.confidence >= 0.95 for c in e1_rows)


def test_berry_smoothie_fires_legacy_gtin_stratum(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """The off-pattern GTIN `5060000099999` is the legacy-GTIN test fixture.
    The cascade must fall through E_1 (no current_gtin match) into E_2
    (legacy_gtins) and apply the obsolescence penalty γ.
    """
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        retailer="sainsburys",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    berry = next(
        c for c in result.classifications
        if c.demand.retailer_key.gtin == "5060000099999"
    )
    assert berry.mapping.evidence is not None
    assert berry.mapping.evidence.stratum == "gtin_legacy", (
        "off-pattern GTIN should fall through to legacy stratum"
    )
    # Obsolescence penalty γ = 0.10 → confidence (1-0.10)(1-0.02)/1 = 0.882
    assert abs(berry.mapping.confidence - 0.882) < 1e-3
    assert berry.mapping.state == "NeedsVerification"
    assert berry.classification == "NeedsVerification"


def test_no_gtin_falafel_bowl_routes_to_review(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """The no-GTIN, no-size 'Falafel Bowl' row is a deliberate ambiguity.

    With TF-IDF (E3b, per D-013), both `falafel` and `bowl` tokens match the
    vocab of *two* ERP products (VG-FALA-350 and VG-FALA-500). The resolver
    fires E3b at the top score, with K_x = 2 — and the FS collision penalty
    correctly drops confidence below auto-allocate, routing to review.
    """
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        retailer="sainsburys",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    no_gtin = [
        c for c in result.classifications
        if c.demand.retailer_key.name.strip() == "Falafel Bowl"
        and c.demand.retailer_key.gtin is None
    ]
    assert len(no_gtin) == 1
    falafel = no_gtin[0]
    assert falafel.mapping.evidence is not None
    # E3b under D-013 supersedes the previous E4 routing — the TF-IDF gate
    # surfaces the ambiguity more cleanly (K_x captures both candidates).
    assert falafel.mapping.evidence.stratum == "tfidf_overlap"
    assert falafel.mapping.evidence.collision_count == 2
    assert falafel.mapping.state == "NeedsVerification"
    assert falafel.classification == "NeedsVerification"


def test_units_to_cases_conversion_is_ceiling(
    erp_snapshot: ErpSnapshot, project_root: Path
) -> None:
    """Sainsbury's publishes consumer units; the pipeline ceiling-divides
    by `case_pack`. For every Resolved row, ⌈units/case_pack⌉ should equal
    `quantity_cases`."""
    result = analyze_week_fulfillment(
        forecast_csv=project_root / "data" / "sainsburys_forecast_week20.csv",
        retailer="sainsburys",
        iso_week="2026-W20",
        erp=erp_snapshot,
    )
    # Build a sku → case_pack map from the snapshot.
    case_pack_by_sku = {p.sku: p.case_pack for p in erp_snapshot.products}

    # Build a key → forecast_units map from the raw CSV via the adapter.
    from verdano.adapters import SAINSBURYS_SPEC, Adapter
    raw = Adapter(SAINSBURYS_SPEC).normalize_forecast(
        project_root / "data" / "sainsburys_forecast_week20.csv"
    )
    raw_units_by_key = {r.retailer_key.model_dump_json(): r.raw_quantity for r in raw}

    import math
    for c in result.classifications:
        if c.mapping.state != "Resolved" or c.mapping.erp_sku is None:
            continue
        cp = case_pack_by_sku[c.mapping.erp_sku]
        key = c.demand.retailer_key.model_dump_json()
        units = raw_units_by_key[key]
        expected = math.ceil(units / cp)
        assert c.demand.quantity_cases == expected, (
            f"{c.demand.retailer_key.name}: {units} units / {cp} pack → "
            f"expected {expected} cases, got {c.demand.quantity_cases}"
        )
