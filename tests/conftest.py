"""Shared pytest fixtures and vcrpy configuration.

The `erp_snapshot` and `project_root` fixtures are lifted here so they're
shared across `tests/pipeline/` and `tests/mcp_server/` without duplication.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
import yaml
from pydantic import TypeAdapter

from verdano.erp.models import (
    Customer,
    InventoryPosition,
    OpenOrder,
    Product,
    Warehouse,
)
from verdano.pipeline import ErpSnapshot

CASSETTE_DIR = Path(__file__).resolve().parent / "erp" / "cassettes" / "test_client"


def _load_cassette_body(name: str) -> bytes:
    with (CASSETTE_DIR / name).open() as f:
        cassette = yaml.safe_load(f)
    body: bytes = cassette["interactions"][0]["response"]["body"]["string"]
    if isinstance(body, bytes) and body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    elif isinstance(body, str):
        body = body.encode()
    return body


_PRODUCTS = TypeAdapter(list[Product])
_CUSTOMERS = TypeAdapter(list[Customer])
_WAREHOUSES = TypeAdapter(list[Warehouse])
_INVENTORY = TypeAdapter(list[InventoryPosition])
_OPEN_ORDERS = TypeAdapter(list[OpenOrder])


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, object]:
    """Scrub the bearer token from recorded cassettes.

    Default record mode is `none` (replay only). Override with
    `--record-mode=once` on the command line to record a fresh cassette.
    """
    return {
        "filter_headers": [
            ("authorization", "Bearer REDACTED"),
            ("Authorization", "Bearer REDACTED"),
        ],
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }


@pytest.fixture(scope="session")
def erp_snapshot() -> ErpSnapshot:
    """An immutable ERP snapshot reconstructed from recorded cassettes."""
    return ErpSnapshot(
        products=_PRODUCTS.validate_json(_load_cassette_body("test_list_products.yaml")),
        customers=_CUSTOMERS.validate_json(
            _load_cassette_body("test_list_customers.yaml")
        ),
        warehouses=_WAREHOUSES.validate_json(
            _load_cassette_body("test_list_warehouses.yaml")
        ),
        inventory=_INVENTORY.validate_json(
            _load_cassette_body("test_list_inventory.yaml")
        ),
        open_orders=_OPEN_ORDERS.validate_json(
            _load_cassette_body("test_list_open_orders.yaml")
        ),
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Path to the project root, where the fixture CSVs live."""
    return Path(__file__).resolve().parent.parent
