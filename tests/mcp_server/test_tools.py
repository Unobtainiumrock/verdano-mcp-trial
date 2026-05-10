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

from verdano.mcp_server.server import build_server
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


def _get_tool_handler(server: Any, tool_name: str) -> Any:
    """FastMCP stores tool handlers in `server._tool_manager._tools` (key=tool name).

    Pull the registered async/sync function out for direct invocation.
    """
    tool = server._tool_manager._tools[tool_name]
    return tool.fn


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
    # Tesco fixture against cassetted ERP — at least one Safe and one AtRiskSevere.
    assert summary["Safe"] >= 1
    assert summary["AtRiskSevere"] >= 1


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
        state = item["mapping"]["state"]
        assert cls in {"Blocked", "AtRiskSevere"} or state == "NeedsVerification"


def test_review_queue_tool_returns_zero_for_safe_dataset(
    project_root: Path, fake_client_factory: Any
) -> None:
    """A known-empty week should return zero review items, not error out."""
    server = build_server(project_root=project_root, erp_client_factory=fake_client_factory)
    handler = _get_tool_handler(server, "list_review_queue_tool")
    result = handler(retailer="tesco", iso_week="9999-W01")
    assert result["count"] == 0
    assert result["items"] == []
