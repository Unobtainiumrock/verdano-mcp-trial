"""MCP server wrapper.

Per the README: "build an MCP server that gives general purpose AI tools like
Claude/ChatGPT useful tools for this workflow." This is the thinnest layer
of the system — it exposes the pipeline functions as MCP tools and serializes
the results as JSON.

Tools (per README minimum bar):
- `analyze_week_fulfillment` — compare retailer forecast vs ERP inventory
   and open orders; classify each line as Safe/AtRisk/AtRiskSevere/Blocked.
- `list_review_queue` — surface the Blocked / NeedsVerification items that
   require operator action, with provenance.

Optional README capabilities also wired up:
- `create_drafts_for_safe_lines` — emit `OrderDraft`s for cleanly-classified
  Safe lines, idempotent via deterministic `external_reference` (D-010 §7).
"""

from verdano.mcp_server.server import build_server, run

__all__ = ["build_server", "run"]
