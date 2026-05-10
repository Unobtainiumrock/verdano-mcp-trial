"""End-to-end ERP client tests, replayed from vcrpy cassettes.

Recording: `uv run pytest tests/erp/ --record-mode=once`. The first run hits
the live API; cassettes land under `tests/erp/cassettes/`. All subsequent
runs replay offline (record_mode is `none` per `tests/conftest.py`).

The bearer token is scrubbed from cassettes via `filter_headers` in
`tests/conftest.py` before commit.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from verdano.erp import (
    Client,
    OrderDraftLine,
    OrderDraftRequest,
)


@pytest.fixture()
def client() -> Iterator[Client]:
    with Client.from_env() as c:
        yield c


@pytest.mark.vcr
def test_health(client: Client) -> None:
    health = client.get_health()
    assert health.status == "ok"


@pytest.mark.vcr
def test_list_products(client: Client) -> None:
    products = client.list_products()
    assert len(products) > 0
    skus = {p.sku for p in products}
    # Falafel SKU referenced by the README order-drafts example must exist.
    assert "VG-FALA-500" in skus
    # Every product carries a positive case_pack and a known temperature band.
    assert all(p.case_pack > 0 for p in products)
    assert all(p.temperature_band in {"chilled", "ambient", "frozen"} for p in products)


@pytest.mark.vcr
def test_list_customers(client: Client) -> None:
    customers = client.list_customers()
    types = {c.type for c in customers}
    assert {"sold_to", "bill_to", "ship_to"} <= types
    # Tesco UK sold-to root referenced by the README example must exist.
    assert any(c.id == "CUST-TESCO-UK" and c.type == "sold_to" for c in customers)


@pytest.mark.vcr
def test_list_warehouses(client: Client) -> None:
    warehouses = client.list_warehouses()
    assert len(warehouses) >= 1
    bands = {w.temperature_band for w in warehouses}
    # Trial fixtures cover at least chilled and ambient.
    assert {"chilled", "ambient"} <= bands


@pytest.mark.vcr
def test_list_inventory(client: Client) -> None:
    positions = client.list_inventory()
    assert len(positions) > 0
    assert all(p.available_cases >= 0 for p in positions)
    assert all(p.allocated_cases >= 0 for p in positions)


@pytest.mark.vcr
def test_list_open_orders(client: Client) -> None:
    orders = client.list_open_orders()
    assert all(len(o.lines) >= 1 for o in orders)


@pytest.mark.vcr
def test_create_order_draft_is_idempotent(client: Client) -> None:
    """Same external_reference returns the existing draft on re-POST."""
    request = OrderDraftRequest(
        external_reference="verdano-trial-smoke-001",
        sold_to_customer_id="CUST-TESCO-UK",
        bill_to_customer_id="BILL-TESCO-HQ",
        ship_to_location_id="SHIP-TESCO-DAV",
        required_date=date(2026, 5, 13),
        lines=[OrderDraftLine(sku="VG-FALA-500", quantity_cases=8)],
        notes="ERP client smoke test",
    )
    first = client.create_order_draft(request)
    second = client.create_order_draft(request)
    # Same external_reference must yield the same draft_id; second call is a
    # no-op replay rather than a fresh creation.
    assert first.draft_id == second.draft_id
    assert second.status == "existing"


@pytest.mark.vcr
def test_list_order_drafts_includes_smoke_draft(client: Client) -> None:
    drafts = client.list_order_drafts()
    refs = {d.external_reference for d in drafts}
    assert "verdano-trial-smoke-001" in refs
    smoke = next(d for d in drafts if d.external_reference == "verdano-trial-smoke-001")
    assert smoke.payload.sold_to_customer_id == "CUST-TESCO-UK"
    assert smoke.payload.lines[0].sku == "VG-FALA-500"
