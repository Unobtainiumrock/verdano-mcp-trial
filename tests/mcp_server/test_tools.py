"""MCP server tool tests.

Drive each tool via the FastMCP-registered Python function (calling the
underlying handler directly). The ERP client is faked from cassette data so
these tests run fully offline and don't require live network.

This is a smoke-test of the `analyze_week_fulfillment` and `list_review_queue`
tools. Draft creation is exercised against the cassette-recorded ERP behavior
where possible; the third tool exists primarily as a wired-up surface.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from verdano.mcp_server.server import build_server, get_tool_handler
from verdano.pipeline import ErpSnapshot


@pytest.fixture()
def fake_client_factory(erp_snapshot: ErpSnapshot) -> Any:
    """A factory returning a context-managed mock client driven by the snapshot."""
    @contextmanager
    def factory():  # type: ignore[no-untyped-def]
        client = MagicMock()
        client.list_products.return_value = erp_snapshot.products
        client.list_customers.return_value = erp_snapshot.customers
        client.list_warehouses.return_value = erp_snapshot.warehouses
        client.list_inventory.return_value = erp_snapshot.inventory
        client.list_open_orders.return_value = erp_snapshot.open_orders
        yield client

    return factory


_get_tool_handler = get_tool_handler


def test_analyze_tool_classifies_tesco_w20(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "analyze_week_fulfillment_tool")
    result = handler(retailer="tesco", iso_week="2026-W20")
    assert result["retailer"] == "tesco"
    assert result["iso_week"] == "2026-W20"
    summary = result["summary"]
    assert sum(summary.values()) == 12
    assert summary["Safe"] >= 1
    assert summary["AtRiskSevere"] >= 1
    assert summary.get("NeedsVerification", 0) + summary.get("Blocked", 0) >= 0


def test_review_queue_tool_includes_only_review_items(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "list_review_queue_tool")
    result = handler(retailer="sainsburys", iso_week="2026-W20")
    items = result["items"]
    # Sainsbury fixture has 3 review-y rows: berry smoothie (legacy gtin),
    # falafel bowl (no gtin), plus any AtRiskSevere supply outcomes.
    assert result["count"] == len(items)
    assert result["count"] >= 2
    for item in items:
        cls = item["classification"]
        assert cls in {"Blocked", "AtRiskSevere", "NeedsVerification"}


def test_review_queue_tool_returns_zero_for_safe_dataset(
    project_root: Path, fake_client_factory: Any
) -> None:
    """A known-empty week should return zero review items, not error out."""
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "list_review_queue_tool")
    result = handler(retailer="tesco", iso_week="9999-W01")
    assert result["count"] == 0
    assert result["items"] == []


# -- 4c: Draft tool tests -----------------------------------------------

def test_create_drafts_tool_invalid_date_returns_error(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "create_drafts_for_safe_lines_tool")
    result = handler(
        retailer="tesco", iso_week="2026-W20",
        ship_to_location_id="SHIP-TESCO-DAV",
        required_date="not-a-date",
    )
    assert "error" in result
    assert "invalid required_date" in result["error"]


def test_create_drafts_tool_invalid_iso_week_returns_error(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "create_drafts_for_safe_lines_tool")
    result = handler(
        retailer="tesco", iso_week="bad-week",
        ship_to_location_id="SHIP-TESCO-DAV",
        required_date="2026-05-13",
    )
    assert "error" in result
    assert "invalid iso_week" in result["error"]


def test_create_drafts_tool_unknown_ship_to_returns_error(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "create_drafts_for_safe_lines_tool")
    result = handler(
        retailer="tesco", iso_week="2026-W20",
        ship_to_location_id="SHIP-NONEXISTENT",
        required_date="2026-05-13",
    )
    assert "error" in result


# -- 4d: Invalid iso_week on analyze and review tools ------------------

def test_analyze_tool_rejects_bad_iso_week(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "analyze_week_fulfillment_tool")
    result = handler(retailer="tesco", iso_week="week20")
    assert "error" in result


def test_review_tool_rejects_bad_iso_week(
    project_root: Path, fake_client_factory: Any
) -> None:
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "list_review_queue_tool")
    result = handler(retailer="tesco", iso_week="2026W20")
    assert "error" in result


# -- 4e: Exact count assertions -----------------------------------------

def test_sainsburys_review_queue_exact_count(
    project_root: Path, fake_client_factory: Any
) -> None:
    """Sainsbury's has exactly 2 NeedsVerification rows (berry + falafel)."""
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "list_review_queue_tool")
    result = handler(retailer="sainsburys", iso_week="2026-W20")
    nv = [i for i in result["items"] if i["classification"] == "NeedsVerification"]
    assert len(nv) == 2


def test_tesco_analyze_exact_line_count(
    project_root: Path, fake_client_factory: Any
) -> None:
    """Tesco fixture produces exactly 12 classification lines."""
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "analyze_week_fulfillment_tool")
    result = handler(retailer="tesco", iso_week="2026-W20")
    assert sum(result["summary"].values()) == 12
