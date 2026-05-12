"""Unit tests for FTPCalculator.

Covers warehouse-band filtering, open-order week filtering,
sold_to_customer_id=None conservative path, negative FTP clamping,
and unknown SKU behavior.
"""

from __future__ import annotations

from datetime import date, datetime

from cpg_reconciler.allocation.ftp import FTPCalculator
from cpg_reconciler.erp.models import InventoryPosition, OpenOrder, OrderLine, Product, Warehouse

_NOW = datetime(2026, 5, 10, 0, 0, 0)


def _product(sku: str, band: str = "chilled", case_pack: int = 6) -> Product:
    return Product(
        sku=sku, name=sku, category="test", temperature_band=band,
        case_pack=case_pack, current_gtins=[], legacy_gtins=[], aliases=[],
        status="active",
    )


def _warehouse(wid: str, band: str = "chilled") -> Warehouse:
    return Warehouse(id=wid, name=wid, temperature_band=band)


def _inventory(sku: str, wid: str, avail: int, alloc: int = 0) -> InventoryPosition:
    return InventoryPosition(
        sku=sku, warehouse_id=wid,
        available_cases=avail, allocated_cases=alloc, as_of=_NOW,
    )


def _order(
    sold_to: str, sku: str, qty: int, req: date = date(2026, 5, 12),
) -> OpenOrder:
    return OpenOrder(
        order_id=f"ORD-{sku}", sold_to_customer_id=sold_to,
        bill_to_customer_id="BILL", ship_to_location_id="SHIP",
        required_date=req,
        lines=[OrderLine(sku=sku, quantity_cases=qty)],
    )


def test_chilled_sku_only_sees_chilled_warehouse() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A", "chilled")],
        warehouses=[_warehouse("WH-C", "chilled"), _warehouse("WH-A", "ambient")],
        inventory=[
            _inventory("SKU-A", "WH-C", 100),
            _inventory("SKU-A", "WH-A", 50),
        ],
        open_orders=[],
    )
    assert ftp.free_to_promise("SKU-A", "2026-W20", None) == 100


def test_open_orders_outside_target_week_excluded() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A")],
        warehouses=[_warehouse("WH-C")],
        inventory=[_inventory("SKU-A", "WH-C", 100)],
        open_orders=[_order("CUST", "SKU-A", 30, date(2026, 5, 19))],
    )
    assert ftp.free_to_promise("SKU-A", "2026-W20", "CUST") == 100


def test_open_orders_in_target_week_subtracted() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A")],
        warehouses=[_warehouse("WH-C")],
        inventory=[_inventory("SKU-A", "WH-C", 100)],
        open_orders=[_order("CUST", "SKU-A", 30, date(2026, 5, 12))],
    )
    assert ftp.free_to_promise("SKU-A", "2026-W20", "CUST") == 70


def test_sold_to_none_subtracts_all_retailers() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A")],
        warehouses=[_warehouse("WH-C")],
        inventory=[_inventory("SKU-A", "WH-C", 100)],
        open_orders=[
            _order("CUST-A", "SKU-A", 20, date(2026, 5, 12)),
            _order("CUST-B", "SKU-A", 10, date(2026, 5, 13)),
        ],
    )
    assert ftp.free_to_promise("SKU-A", "2026-W20", None) == 70


def test_negative_ftp_clamped_to_zero() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A")],
        warehouses=[_warehouse("WH-C")],
        inventory=[_inventory("SKU-A", "WH-C", 10)],
        open_orders=[_order("CUST", "SKU-A", 50, date(2026, 5, 12))],
    )
    assert ftp.free_to_promise("SKU-A", "2026-W20", "CUST") == 0


def test_unknown_sku_returns_zero() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A")],
        warehouses=[_warehouse("WH-C")],
        inventory=[_inventory("SKU-A", "WH-C", 100)],
        open_orders=[],
    )
    assert ftp.free_to_promise("SKU-UNKNOWN", "2026-W20", None) == 0


def test_allocated_cases_subtracted_from_available() -> None:
    ftp = FTPCalculator(
        products=[_product("SKU-A")],
        warehouses=[_warehouse("WH-C")],
        inventory=[_inventory("SKU-A", "WH-C", 100, alloc=40)],
        open_orders=[],
    )
    assert ftp.free_to_promise("SKU-A", "2026-W20", None) == 60
