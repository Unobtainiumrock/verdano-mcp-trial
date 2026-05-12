"""Thin httpx wrapper around the Corvera trial ERP API.

The ERP has no OpenAPI page (per ERP API.md), so this client is hand-rolled.
One method per endpoint, bearer auth from `.env`, typed exceptions on non-2xx.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import certifi
import httpx
from pydantic import TypeAdapter

from cpg_reconciler.config import Settings, load_settings
from cpg_reconciler.erp.models import (
    Customer,
    Health,
    InventoryPosition,
    OpenOrder,
    OrderDraftCreated,
    OrderDraftRecord,
    OrderDraftRequest,
    Product,
    Warehouse,
)

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


_CONTEXT_CACHE: ssl.SSLContext | None = None


def _resolve_ssl_context() -> ssl.SSLContext:
    """Return an `ssl.SSLContext` for HTTPS verification.

    CA bundle resolution order:
      1. `SSL_CERT_FILE` if set (standard Python idiom — explicit user override).
      2. `certifi.where()` plus any extras from `REQUESTS_CA_BUNDLE` and
         `NODE_EXTRA_CA_CERTS`, concatenated into a single tmpfile. This makes
         the client work transparently in dev environments behind a TLS-MITM
         proxy (e.g., mitmproxy) without forcing users to hand-build a bundle.
      3. Otherwise certifi alone.

    Returning an `SSLContext` (rather than a bundle path) avoids httpx's
    `verify=<str>` deprecation warning and lets callers reuse the same
    context across requests. Cached for the process lifetime.
    """
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is not None:
        return _CONTEXT_CACHE

    explicit = os.environ.get("SSL_CERT_FILE")
    if explicit and os.path.isfile(explicit):
        _CONTEXT_CACHE = ssl.create_default_context(cafile=explicit)
        return _CONTEXT_CACHE

    extras = [
        os.environ[var]
        for var in ("REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")
        if var in os.environ and os.path.isfile(os.environ[var])
    ]
    if not extras:
        _CONTEXT_CACHE = ssl.create_default_context(cafile=certifi.where())
        return _CONTEXT_CACHE

    bundle_bytes = Path(certifi.where()).read_bytes()
    for extra in extras:
        bundle_bytes += b"\n" + Path(extra).read_bytes()
    fd, path = tempfile.mkstemp(suffix=".pem", prefix="verdano-ca-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(bundle_bytes)
        _CONTEXT_CACHE = ssl.create_default_context(cafile=path)
    finally:
        os.unlink(path)
    return _CONTEXT_CACHE


class ERPError(Exception):
    """Base class for ERP client errors."""


class ERPHTTPError(ERPError):
    """Raised when the ERP returns a non-2xx response."""

    _MAX_BODY_REPR = 200

    def __init__(self, status_code: int, body: Any, request_url: str) -> None:
        body_repr = repr(body)
        if len(body_repr) > self._MAX_BODY_REPR:
            body_repr = body_repr[: self._MAX_BODY_REPR] + "..."
        super().__init__(f"ERP {status_code} for {request_url}: {body_repr}")
        self.status_code = status_code
        self.body = body
        self.request_url = request_url


_PRODUCTS = TypeAdapter(list[Product])
_CUSTOMERS = TypeAdapter(list[Customer])
_WAREHOUSES = TypeAdapter(list[Warehouse])
_INVENTORY = TypeAdapter(list[InventoryPosition])
_OPEN_ORDERS = TypeAdapter(list[OpenOrder])
_ORDER_DRAFTS = TypeAdapter(list[OrderDraftRecord])


class Client(AbstractContextManager["Client"]):
    """ERP HTTP client.

    Construct via `Client.from_env()` for normal use, or pass an explicit
    `Settings` for tests. Use as a context manager so the underlying
    `httpx.Client` is closed deterministically.
    """

    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self._settings = settings
        self._http = http or httpx.Client(
            base_url=str(settings.erp_base_url).rstrip("/"),
            headers={"Authorization": f"Bearer {settings.erp_api_key.get_secret_value()}"},
            timeout=DEFAULT_TIMEOUT,
            verify=_resolve_ssl_context(),
        )

    @classmethod
    def from_env(cls) -> Self:
        return cls(load_settings())

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> dict[str, Any] | list[Any]:
        response = self._http.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                body: Any = response.json()
            except ValueError:
                body = response.text
            raise ERPHTTPError(response.status_code, body, str(response.request.url))
        return response.json()  # type: ignore[no-any-return]

    def get_health(self) -> Health:
        return Health.model_validate(self._request("GET", "/health"))

    def list_products(self) -> list[Product]:
        return _PRODUCTS.validate_python(self._request("GET", "/erp/products"))

    def list_customers(self) -> list[Customer]:
        return _CUSTOMERS.validate_python(self._request("GET", "/erp/customers"))

    def list_warehouses(self) -> list[Warehouse]:
        return _WAREHOUSES.validate_python(self._request("GET", "/erp/warehouses"))

    def list_inventory(
        self, sku: str | None = None, warehouse_id: str | None = None
    ) -> list[InventoryPosition]:
        params = {k: v for k, v in {"sku": sku, "warehouse_id": warehouse_id}.items() if v}
        return _INVENTORY.validate_python(self._request("GET", "/erp/inventory", params=params))

    def list_open_orders(
        self, retailer: str | None = None, sku: str | None = None
    ) -> list[OpenOrder]:
        params = {k: v for k, v in {"retailer": retailer, "sku": sku}.items() if v}
        return _OPEN_ORDERS.validate_python(self._request("GET", "/erp/open-orders", params=params))

    def create_order_draft(self, draft: OrderDraftRequest) -> OrderDraftCreated:
        """Idempotent: reusing the same `external_reference` returns the existing draft.

        On a fresh `external_reference` the response carries `status="created"`;
        on a re-POST it carries `status="existing"` and the same `draft_id`.
        """
        payload = draft.model_dump(mode="json", exclude_none=True)
        return OrderDraftCreated.model_validate(
            self._request("POST", "/erp/order-drafts", json=payload)
        )

    def list_order_drafts(self) -> list[OrderDraftRecord]:
        return _ORDER_DRAFTS.validate_python(self._request("GET", "/erp/order-drafts"))
