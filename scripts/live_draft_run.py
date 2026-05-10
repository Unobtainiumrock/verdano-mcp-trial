"""Operational live-run driver — exercises the MCP tools against the real ERP.

Per Plan extension #2 Step 3. Runs the MCP-tool handler functions directly
against `Client.from_env`, hitting the production trial-ERP at
`https://erp.corvera.ai`. Confirms:

  1. analyze + list_review tools work end-to-end.
  2. create_drafts at SHIP-TESCO-DAV (chilled) creates real drafts; ambient
     SKUs are correctly skipped under the new pre-filter.
  3. create_drafts at SHIP-TESCO-RDG (ambient) creates the complementary set.
  4. Re-running both calls is idempotent (drafts_existing populated, no new
     draft_ids).
  5. list_order_drafts (raw client) shows the script's full footprint.

Output is structured per-call dicts. Nothing is committed to disk by this
script; the captured run-log lives in `docs/live-run-results.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verdano.erp import Client
from verdano.mcp_server.server import build_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RETAILER = "tesco"
WEEK = "2026-W20"
REQUIRED_DATE = "2026-05-13"
SHIP_TOS = [
    ("SHIP-TESCO-DAV", "chilled"),
    ("SHIP-TESCO-RDG", "ambient"),
]


def _summarize(label: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {label} ===")
    print(json.dumps(payload, indent=2, default=str))


def _get_handler(server: Any, name: str) -> Any:
    return server._tool_manager._tools[name].fn


def main() -> None:
    server = build_server(project_root=PROJECT_ROOT)
    analyze = _get_handler(server, "analyze_week_fulfillment_tool")
    review = _get_handler(server, "list_review_queue_tool")
    drafts_tool = _get_handler(server, "create_drafts_for_safe_lines_tool")

    # 1. Read-only sanity.
    _summarize(
        f"analyze_week_fulfillment_tool({RETAILER}, {WEEK})",
        analyze(retailer=RETAILER, iso_week=WEEK),
    )
    _summarize(
        f"list_review_queue_tool({RETAILER}, {WEEK})",
        review(retailer=RETAILER, iso_week=WEEK),
    )

    # 2 / 3. Mutating tool — first run, both ship-tos.
    first_run: dict[str, dict[str, Any]] = {}
    for ship_to, band in SHIP_TOS:
        result = drafts_tool(
            retailer=RETAILER,
            iso_week=WEEK,
            ship_to_location_id=ship_to,
            required_date=REQUIRED_DATE,
        )
        first_run[ship_to] = result
        _summarize(
            f"FIRST run create_drafts_for_safe_lines_tool({ship_to}, {band})",
            result,
        )

    # 4. Idempotency — same args, second run.
    print("\n=== IDEMPOTENCY RE-RUN ===")
    for ship_to, band in SHIP_TOS:
        result = drafts_tool(
            retailer=RETAILER,
            iso_week=WEEK,
            ship_to_location_id=ship_to,
            required_date=REQUIRED_DATE,
        )
        first_created = {d["draft_id"] for d in first_run[ship_to]["drafts_created"]}
        first_existing = {d["draft_id"] for d in first_run[ship_to]["drafts_existing"]}
        first_known = first_created | first_existing
        second_existing = {d["draft_id"] for d in result["drafts_existing"]}
        second_created = {d["draft_id"] for d in result["drafts_created"]}

        # The second run must NOT create any new draft_ids that weren't seen
        # the first time. All previously-created draft_ids must now appear in
        # drafts_existing.
        leaked = second_created - first_known
        missed = first_known - (second_existing | second_created)
        assert not leaked, f"second run leaked new draft_ids: {leaked}"
        assert not missed, f"second run dropped previously-known drafts: {missed}"
        print(
            f"  {ship_to} ({band}): "
            f"first run created={len(first_created)} existing={len(first_existing)} | "
            f"second run created={len(second_created)} existing={len(second_existing)} ✓"
        )

    # 5. Final live inventory of all drafts under our key.
    with Client.from_env() as client:
        all_drafts = client.list_order_drafts()
    verdano_drafts = [d for d in all_drafts if d.external_reference.startswith("verdano-")]
    print("\n=== LIVE list_order_drafts (verdano-prefixed) ===")
    print(f"Total verdano drafts in ERP: {len(verdano_drafts)}")
    for d in verdano_drafts:
        line = d.payload.lines[0]
        print(
            f"  {d.draft_id}  ext_ref={d.external_reference[:32]}...  "
            f"sku={line.sku}  qty={line.quantity_cases}  "
            f"ship_to={d.payload.ship_to_location_id}"
        )


if __name__ == "__main__":
    main()
