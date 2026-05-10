"""Tests for the depot-string → ship_to resolver."""

from __future__ import annotations

import pytest

from verdano.erp.models import Customer
from verdano.mapping.depot import resolve_depot


def _ship_to(
    id: str, name: str, parent: str = "CUST-TESCO-UK", wh: str = "WH-C",
) -> Customer:
    return Customer(
        id=id, type="ship_to", name=name,
        parent_id=parent, warehouse_id=wh,
    )


@pytest.fixture()
def tesco_customers() -> list[Customer]:
    return [
        Customer(id="CUST-TESCO-UK", type="sold_to", name="Tesco UK", parent_id=None, warehouse_id=None),
        Customer(id="BILL-TESCO", type="bill_to", name="Tesco Billing", parent_id="CUST-TESCO-UK", warehouse_id=None),
        _ship_to("SHIP-TESCO-DAV", "Tesco Daventry Chilled DC"),
        _ship_to("SHIP-TESCO-RDG", "Tesco Reading Ambient DC"),
    ]


class TestDepotResolver:

    def test_exact_substring_match(self, tesco_customers: list[Customer]) -> None:
        result = resolve_depot("Daventry Chilled", tesco_customers, "tesco")
        assert result == "SHIP-TESCO-DAV"

    def test_exact_substring_reading(self, tesco_customers: list[Customer]) -> None:
        result = resolve_depot("Reading Ambient", tesco_customers, "tesco")
        assert result == "SHIP-TESCO-RDG"

    def test_case_insensitive(self, tesco_customers: list[Customer]) -> None:
        result = resolve_depot("daventry chilled", tesco_customers, "tesco")
        assert result == "SHIP-TESCO-DAV"

    def test_fuzzy_match_partial(self, tesco_customers: list[Customer]) -> None:
        result = resolve_depot("Daventry", tesco_customers, "tesco")
        assert result == "SHIP-TESCO-DAV"

    def test_no_match_returns_none(self, tesco_customers: list[Customer]) -> None:
        result = resolve_depot("Birmingham Frozen", tesco_customers, "tesco")
        assert result is None

    def test_empty_label_returns_none(self, tesco_customers: list[Customer]) -> None:
        result = resolve_depot("", tesco_customers, "tesco")
        assert result is None

    def test_cross_retailer_filtered(self, tesco_customers: list[Customer]) -> None:
        """Searching for a Sainsbury's location among Tesco customers returns None."""
        result = resolve_depot("Daventry Chilled", tesco_customers, "sainsburys")
        assert result is None

    def test_sainsburys_all_depots(self) -> None:
        customers = [
            _ship_to("SHIP-SAINS-CHILLED", "Sainsbury's All Depots - Chilled", parent="CUST-SAINS-UK"),
            _ship_to("SHIP-SAINS-AMBIENT", "Sainsbury's All Depots - Ambient", parent="CUST-SAINS-UK"),
        ]
        result = resolve_depot("All Depots", customers, "sainsburys")
        # Multiple substring matches; fuzzy picks the best one
        assert result in ("SHIP-SAINS-CHILLED", "SHIP-SAINS-AMBIENT")

    def test_no_ship_to_customers_returns_none(self) -> None:
        customers = [
            Customer(id="CUST-TESCO-UK", type="sold_to", name="Tesco UK", parent_id=None, warehouse_id=None),
        ]
        result = resolve_depot("Daventry", customers, "tesco")
        assert result is None
