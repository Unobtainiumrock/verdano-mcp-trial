"""Free-to-promise calculator.

Formalism §5.1:

    ftp(s, W, r) = Σ_{w ∈ W_compat(s)} (a(s,w) − α(s,w))
                   − Σ_{o ∈ O(r, s, W)} q(o)

where W_compat(s) is the set of warehouses with temperature_band matching the
product's temperature_band.
"""

from __future__ import annotations

from datetime import date

from cpg_reconciler.erp.models import (
    InventoryPosition,
    OpenOrder,
    Product,
    Warehouse,
)


def _iso_week_contains(iso_week: str, d: date) -> bool:
    """Return True iff the calendar date `d` falls in `iso_week` ('YYYY-Www')."""
    iso = d.isocalendar()
    candidate = f"{iso.year}-W{iso.week:02d}"
    return candidate == iso_week


class FTPCalculator:
    """Pre-indexed FTP calculator over an ERP snapshot.

    Pre-builds the warehouse-by-band lookup, the inventory-by-sku index, and
    the open-orders-by-(retailer-customer-id, sku) index at construction time
    so per-line FTP queries are O(1)+ small.
    """

    def __init__(
        self,
        products: list[Product],
        warehouses: list[Warehouse],
        inventory: list[InventoryPosition],
        open_orders: list[OpenOrder],
    ) -> None:
        self._products = {p.sku: p for p in products}
        self._warehouses = {w.id: w for w in warehouses}

        # warehouses_by_band: temperature → list[warehouse_id]
        self._warehouses_by_band: dict[str, list[str]] = {}
        for w in warehouses:
            self._warehouses_by_band.setdefault(w.temperature_band, []).append(w.id)

        # inventory_by_sku: sku → {warehouse_id: (available, allocated)}
        self._inventory_by_sku: dict[str, dict[str, tuple[int, int]]] = {}
        for ip in inventory:
            self._inventory_by_sku.setdefault(ip.sku, {})[ip.warehouse_id] = (
                ip.available_cases,
                ip.allocated_cases,
            )

        # open orders indexed by (sold_to_customer_id, sku) for fast retailer-aware sum.
        self._open_lines: list[tuple[str, str, int, date]] = []
        for o in open_orders:
            for line in o.lines:
                self._open_lines.append(
                    (o.sold_to_customer_id, line.sku, line.quantity_cases, o.required_date)
                )

    # -------------------------------------------------------------- public API

    def free_to_promise(
        self,
        sku: str,
        iso_week: str,
        sold_to_customer_id: str | None,
    ) -> int:
        """Return cases free-to-promise for `sku` in `iso_week`.

        If `sold_to_customer_id` is None, the open-order subtraction sums
        across *all* retailers (conservative stance — assume any committed
        demand competes for the same supply pool).

        Returns 0 (not negative) when the formula is negative; a negative FTP
        is operationally just "we have nothing", and downstream classification
        treats 0 as the boundary.
        """
        product = self._products.get(sku)
        if product is None:
            return 0

        compatible_warehouses = self._warehouses_by_band.get(
            product.temperature_band, []
        )
        net_inventory = 0
        sku_inventory = self._inventory_by_sku.get(sku, {})
        for w_id in compatible_warehouses:
            avail, alloc = sku_inventory.get(w_id, (0, 0))
            net_inventory += avail - alloc

        committed = 0
        for cust_id, line_sku, qty, req_date in self._open_lines:
            if line_sku != sku:
                continue
            if sold_to_customer_id is not None and cust_id != sold_to_customer_id:
                continue
            if not _iso_week_contains(iso_week, req_date):
                continue
            committed += qty

        return max(0, net_inventory - committed)
