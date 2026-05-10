"""Draft-creation logic extracted from the MCP server tool.

Takes an ``AnalysisResult``, ERP snapshot, and an ``erp.Client`` (for the
actual ``create_order_draft`` calls) and returns a structured result dict.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from verdano.canonical import RetailerCode
from verdano.erp import Client, ERPHTTPError, OrderDraftLine, OrderDraftRequest
from verdano.erp.models import Customer, Product, Warehouse
from verdano.pipeline.analyze import AnalysisResult, customer_for_retailer


def _deterministic_external_reference(
    retailer: RetailerCode, sku: str, iso_week: str, ship_to: str
) -> str:
    """Per D-010 §7: external_reference = sha256(retailer | sku | week | ship_to)."""
    payload = f"{retailer}|{sku}|{iso_week}|{ship_to}".encode()
    return f"verdano-{hashlib.sha256(payload).hexdigest()[:32]}"


def create_drafts(
    *,
    result: AnalysisResult,
    client: Client,
    customers: list[Customer],
    products: list[Product],
    warehouses: list[Warehouse],
    retailer: RetailerCode,
    iso_week: str,
    required_date: date,
    ship_to_location_id: str,
) -> dict[str, Any]:
    """Create ERP order drafts for every Safe-classified line.

    Returns a dict with keys: retailer, iso_week, ship_to_location_id,
    ship_to_band, drafts_created, drafts_existing, skipped, failed.
    """
    customer = customer_for_retailer(customers, retailer)
    if customer is None:
        return {"error": f"no sold-to customer found for {retailer}"}

    bill_to = next(
        (c for c in customers if c.type == "bill_to" and c.parent_id == customer.id),
        None,
    )
    if bill_to is None:
        return {"error": f"no bill-to customer found under sold-to {customer.id}"}

    ship_to = next(
        (c for c in customers if c.type == "ship_to" and c.id == ship_to_location_id),
        None,
    )
    if ship_to is None:
        return {"error": f"ship_to_location_id {ship_to_location_id} not found"}

    warehouses_by_id = {w.id: w for w in warehouses}
    ship_to_band: str | None = (
        warehouses_by_id[ship_to.warehouse_id].temperature_band
        if ship_to.warehouse_id and ship_to.warehouse_id in warehouses_by_id
        else None
    )
    products_by_sku = {p.sku: p for p in products}

    drafts_created: list[dict[str, Any]] = []
    drafts_existing: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for c in result.classifications:
        if c.classification != "Safe" or c.erp_sku is None:
            continue
        if c.demand.quantity_cases < 1:
            continue

        product = products_by_sku.get(c.erp_sku)
        product_band = product.temperature_band if product else None
        if (
            ship_to_band is not None
            and product_band is not None
            and product_band != ship_to_band
        ):
            skipped.append({
                "sku": c.erp_sku,
                "quantity_cases": c.demand.quantity_cases,
                "reason": "temperature_band_mismatch",
                "product_band": product_band,
                "ship_to_band": ship_to_band,
            })
            continue

        ext_ref = _deterministic_external_reference(
            retailer, c.erp_sku, iso_week, ship_to_location_id,
        )
        request = OrderDraftRequest(
            external_reference=ext_ref,
            sold_to_customer_id=customer.id,
            bill_to_customer_id=bill_to.id,
            ship_to_location_id=ship_to_location_id,
            required_date=required_date,
            lines=[
                OrderDraftLine(sku=c.erp_sku, quantity_cases=c.demand.quantity_cases)
            ],
            notes=f"verdano-mcp auto-draft for {retailer} {iso_week}",
        )
        try:
            response = client.create_order_draft(request)
        except ERPHTTPError as e:
            failed.append({
                "sku": c.erp_sku,
                "quantity_cases": c.demand.quantity_cases,
                "external_reference": ext_ref,
                "status_code": e.status_code,
                "body": e.body,
            })
            continue

        bucket = drafts_created if response.status == "created" else drafts_existing
        bucket.append({
            "draft_id": response.draft_id,
            "status": response.status,
            "external_reference": ext_ref,
            "sku": c.erp_sku,
            "quantity_cases": c.demand.quantity_cases,
        })

    return {
        "retailer": retailer,
        "iso_week": iso_week,
        "ship_to_location_id": ship_to_location_id,
        "ship_to_band": ship_to_band,
        "drafts_created": drafts_created,
        "drafts_existing": drafts_existing,
        "skipped": skipped,
        "failed": failed,
    }
