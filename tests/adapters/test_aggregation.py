"""Unit tests for Adapter._aggregate_to_weekly.

Covers the promo-flag OR-ing, note deduplication, quantity summing, and
grouping-key correctness that the Tesco vertical slice exercises only
implicitly.
"""

from __future__ import annotations

from cpg_reconciler.adapters.adapter import Adapter
from cpg_reconciler.adapters.raw import RawDemandLine
from cpg_reconciler.canonical import RetailerProductKey


def _key(name: str = "Product A", gtin: str | None = None) -> RetailerProductKey:
    return RetailerProductKey(retailer="tesco", name=name, gtin=gtin)


def _raw(
    *,
    iso_week: str = "2026-W20",
    key: RetailerProductKey | None = None,
    location: str = "Daventry",
    qty: int = 10,
    promo: bool = False,
    notes: str | None = None,
) -> RawDemandLine:
    return RawDemandLine(
        retailer="tesco",
        iso_week=iso_week,
        retailer_key=key or _key(),
        location_label=location,
        raw_quantity=qty,
        raw_unit_mode="cases",
        promo_flag=promo,
        notes=notes,
        inferred=False,
    )


class TestAggregateToWeekly:
    def test_quantities_summed(self) -> None:
        rows = [_raw(qty=30), _raw(qty=50), _raw(qty=20)]
        agg = Adapter._aggregate_to_weekly(rows)
        assert len(agg) == 1
        assert agg[0].raw_quantity == 100

    def test_promo_flag_or(self) -> None:
        """If any day is promo, the weekly row should be promo."""
        rows = [
            _raw(promo=False),
            _raw(promo=True),
            _raw(promo=False),
        ]
        agg = Adapter._aggregate_to_weekly(rows)
        assert agg[0].promo_flag is True

    def test_promo_flag_all_false(self) -> None:
        rows = [_raw(promo=False), _raw(promo=False)]
        agg = Adapter._aggregate_to_weekly(rows)
        assert agg[0].promo_flag is False

    def test_notes_dedup_and_sort(self) -> None:
        """Duplicate notes should be collapsed; unique notes sorted and joined."""
        rows = [
            _raw(notes="promo bay"),
            _raw(notes="fixture expansion"),
            _raw(notes="promo bay"),
        ]
        agg = Adapter._aggregate_to_weekly(rows)
        assert agg[0].notes == "fixture expansion; promo bay"

    def test_notes_none_ignored(self) -> None:
        rows = [_raw(notes=None), _raw(notes="note A"), _raw(notes=None)]
        agg = Adapter._aggregate_to_weekly(rows)
        assert agg[0].notes == "note A"

    def test_notes_all_none(self) -> None:
        rows = [_raw(notes=None), _raw(notes=None)]
        agg = Adapter._aggregate_to_weekly(rows)
        assert agg[0].notes is None

    def test_different_products_stay_separate(self) -> None:
        key_a = _key("Product A")
        key_b = _key("Product B")
        rows = [_raw(key=key_a, qty=10), _raw(key=key_b, qty=20)]
        agg = Adapter._aggregate_to_weekly(rows)
        assert len(agg) == 2
        by_name = {r.retailer_key.name: r for r in agg}
        assert by_name["Product A"].raw_quantity == 10
        assert by_name["Product B"].raw_quantity == 20

    def test_different_locations_stay_separate(self) -> None:
        rows = [
            _raw(location="Daventry", qty=10),
            _raw(location="Reading", qty=20),
        ]
        agg = Adapter._aggregate_to_weekly(rows)
        assert len(agg) == 2
        by_loc = {r.location_label: r for r in agg}
        assert by_loc["Daventry"].raw_quantity == 10
        assert by_loc["Reading"].raw_quantity == 20

    def test_different_weeks_stay_separate(self) -> None:
        rows = [
            _raw(iso_week="2026-W19", qty=10),
            _raw(iso_week="2026-W20", qty=20),
        ]
        agg = Adapter._aggregate_to_weekly(rows)
        assert len(agg) == 2
