"""Pydantic response/request models for the Verdano trial ERP API.

Field shapes were learned via direct probe of the live endpoints, then
documented here. Keep models *closed* (`extra="forbid"`) so schema drift
fails loudly during recording rather than silently during analysis.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TemperatureBand = Literal["chilled", "ambient", "frozen"]
"""Trial fixtures expose chilled and ambient. `frozen` reserved for completeness."""

CustomerType = Literal["sold_to", "bill_to", "ship_to"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Health(_Strict):
    status: str
    service: str


class Product(_Strict):
    sku: str
    name: str
    category: str
    temperature_band: TemperatureBand
    case_pack: int = Field(gt=0)
    current_gtins: list[str]
    legacy_gtins: list[str]
    aliases: list[str]
    status: str


class Customer(_Strict):
    id: str
    type: CustomerType
    name: str
    parent_id: str | None
    warehouse_id: str | None


class Warehouse(_Strict):
    id: str
    name: str
    temperature_band: TemperatureBand


class InventoryPosition(_Strict):
    sku: str
    warehouse_id: str
    available_cases: int = Field(ge=0)
    allocated_cases: int = Field(ge=0)
    as_of: datetime


class OrderLine(_Strict):
    sku: str
    quantity_cases: int = Field(gt=0)


class OpenOrder(_Strict):
    order_id: str
    sold_to_customer_id: str
    bill_to_customer_id: str
    ship_to_location_id: str
    required_date: date
    lines: list[OrderLine]


OrderDraftStatus = Literal["created", "existing"]


class OrderDraftLine(_Strict):
    sku: str
    quantity_cases: int = Field(gt=0)


class OrderDraftRequest(_Strict):
    """Payload for `POST /erp/order-drafts`.

    Reusing the same `external_reference` is idempotent — the ERP returns
    the existing draft. Derive `external_reference` deterministically (e.g.
    `sha256(retailer | erp_sku | iso_week | ship_to_location_id)`) so reruns
    are safe by construction.
    """

    external_reference: str
    sold_to_customer_id: str
    bill_to_customer_id: str
    ship_to_location_id: str
    required_date: date
    lines: list[OrderDraftLine] = Field(min_length=1)
    notes: str | None = None


class OrderDraftCreated(_Strict):
    """Response shape of `POST /erp/order-drafts`.

    `status` is `"created"` for a new draft and `"existing"` when the
    `external_reference` matched an existing draft (idempotent re-POST).
    """

    draft_id: str
    status: OrderDraftStatus
    validation_warnings: list[str]
    created_at: datetime


class OrderDraftRecord(_Strict):
    """Item shape of `GET /erp/order-drafts`.

    `payload` echoes the request that created the draft.
    """

    draft_id: str
    external_reference: str
    payload: OrderDraftRequest
    validation_warnings: list[str]
    created_at: datetime
