"""MCP server wrapper.

Per the README: "build an MCP server that gives general purpose AI tools like
Claude/ChatGPT useful tools for this workflow." This is the thinnest layer
of the system — it exposes the pipeline functions as MCP tools and serializes
the results as JSON.

Tools:
- ``analyze_week_fulfillment`` — compare retailer forecast vs ERP inventory
  and open orders; classify each line as Safe / AtRisk / AtRiskSevere /
  NeedsVerification / Blocked.
- ``list_review_queue`` — surface Blocked / NeedsVerification items that
  require operator action, with provenance.
- ``create_drafts_for_safe_lines`` — emit ``OrderDraft``s for Safe lines,
  idempotent via deterministic ``external_reference``.
- ``compare_actuals_vs_forecast`` — drift analysis in three modes:
  plausibility, residual, and Markov (D-020, D-024).
"""

from cpg_reconciler.mcp_server.server import build_server, run

__all__ = ["build_server", "run"]
