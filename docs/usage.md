# Usage — Verdano MCP work-trial

Reviewer's guide to running, testing, and exercising the deliverable.

## Quick start

```bash
# 1. Clone and install (uv lockfile is committed; one command).
uv sync

# 2. Set up credentials (only needed for the live MCP tool path; tests work
#    fully offline against recorded cassettes).
cp .env.example .env
# then edit .env and paste in the trial API key from the README brief.

# 3. Confirm everything is wired up (33 tests, fully offline — no .env needed).
uv run pytest

# 4. Run a one-shot analysis (paste into a Python REPL or a script).
#    No `.env` needed — uses cassette-recorded ERP state.
uv run python - <<'PY'
import gzip, yaml
from pathlib import Path
from pydantic import TypeAdapter
from verdano.erp.models import Product, Customer, Warehouse, InventoryPosition, OpenOrder
from verdano.pipeline import ErpSnapshot, analyze_week_fulfillment

cdir = Path("tests/erp/cassettes/test_client")
def load(name, T):
    body = yaml.safe_load((cdir / name).read_text())["interactions"][0]["response"]["body"]["string"]
    if isinstance(body, bytes) and body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return TypeAdapter(T).validate_json(body)

erp = ErpSnapshot(
    products=load("test_list_products.yaml", list[Product]),
    customers=load("test_list_customers.yaml", list[Customer]),
    warehouses=load("test_list_warehouses.yaml", list[Warehouse]),
    inventory=load("test_list_inventory.yaml", list[InventoryPosition]),
    open_orders=load("test_list_open_orders.yaml", list[OpenOrder]),
)

result = analyze_week_fulfillment(
    forecast_csv="tesco_forecast_week20.csv",
    retailer="tesco",
    iso_week="2026-W20",
    erp=erp,
)
print(f"Summary: {dict(result.summary)}")
for c in result.classifications:
    item = c.demand.retailer_key.tesco_item or c.demand.retailer_key.gtin
    print(f"  {c.classification:<14} {item:<10} qty={c.demand.quantity_cases:>3}  ftp={c.ftp_cases}  → {c.erp_sku}")
    print(f"    {c.reason}")
PY
```

This runs the entire pipeline against cassette-recorded ERP state. Replace `tesco` with `sainsburys` and the CSV path to see the Sainsbury fixture path (legacy-GTIN, no-GTIN-fuzzy fallback, units→cases conversion).

## Project layout

```
src/verdano/
├── canonical/         entity contracts (CanonicalDemandLine, MappingResult, etc.)
├── adapters/          single Adapter class + RetailerSpec configs (Tesco, Sainsbury)
├── mapping/           cascade resolver (Fellegi-Sunter + Jaro-Winkler²)
├── allocation/        FTP math + Safe/AtRisk/Blocked classifier
├── pipeline/          analyze_week_fulfillment — end-to-end DAG
├── erp/               hand-rolled HTTP client + Pydantic response models
├── mcp_server/        FastMCP server exposing 3 tools
├── config.py          .env loader (pydantic-settings)
└── logging.py         structlog setup

primitives/
├── ERP/               ontological grounding (out of scope for the build, kept for context)
└── CPG/               ontological core (in scope) — entity-resolution, demand-alignment, allocation, workflow

docs/
├── architecture/
│   ├── formalism.md                       LaTeX math: morphisms, FS posteriors, change-of-basis, water-filling, FSM/DAG
│   ├── verdano-problem-entity-model.md    ER diagram + flowcharts
│   └── storage-runtime-decision.md        Polars + DuckDB decision memo
└── usage.md           this file

DECISIONS.md           chronological D-001..D-011 with rationale + alternatives
working-doc.md         operating index — open questions, locked decisions, gotchas
raw_truth.md           Gemini conversation transcripts (1..9)
prompts-for-gemini.md  prompts for future iterations of MATH-SOT
```

## Running the MCP server

The server speaks stdio for direct use under Claude Desktop or `mcp-cli`:

```bash
uv run python -m verdano.mcp_server
```

For Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "verdano": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/challenge", "run",
               "python", "-m", "verdano.mcp_server"]
    }
  }
}
```

### Tools exposed

| Tool | Purpose |
|---|---|
| `analyze_week_fulfillment_tool(retailer, iso_week)` | Compare retailer forecast vs ERP supply for a given ISO week. Returns Safe / AtRisk / AtRiskSevere / Blocked per line, with operator-readable reasoning. |
| `list_review_queue_tool(retailer, iso_week)` | Filter to only the lines requiring human review (Blocked + AtRiskSevere + low-confidence mappings). The operator's first surface. |
| `create_drafts_for_safe_lines_tool(retailer, iso_week, ship_to_location_id, required_date)` | Create `OrderDraft`s for every Safe-classified line at the given ship_to. Pre-filters cross-band SKUs (returned in `skipped`); catches per-line ERP errors (`failed`). Idempotent by deterministic `external_reference = sha256(retailer, sku, week, ship_to)` so re-runs return `existing` for previously-created drafts. |
| `compare_actuals_vs_forecast_tool(retailer, iso_week_forecast, iso_week_actuals)` | **Lagged-actuals plausibility check**, not classical residual drift (per D-012). Computes ratio `forecast_eaches / max(actuals_eaches, 1)` per resolved SKU, threshold-flags as high/low/ok, segments out promo-flagged forecast rows. The fixture's W19 actuals + W20 forecast forces this framing — Markov-style true drift requires a same-period forecast/actuals pair which the fixture doesn't provide. See [DECISIONS.md D-012](../DECISIONS.md) and [formalism §10](architecture/formalism.md). |

Tools are coarse-grained intentionally (per Gemini iteration 4 + the morphism formalism in `docs/architecture/formalism.md` §6.2) — the LLM gets one round-trip per question.

## Tests — what each suite covers

```bash
uv run pytest -v
```

| Suite | Coverage |
|---|---|
| `tests/erp/` | ERP HTTP client behavior — every endpoint, idempotency invariant, offline cassette replay (8 tests). |
| `tests/pipeline/test_tesco_vertical_slice.py` | End-to-end pipeline against the Tesco fixture: classification, falafel bowl distinctness, Safe-line FTP invariant, determinism (9 tests). |
| `tests/pipeline/test_sainsburys_config_only.py` | Validates that onboarding Sainsbury required *no new Python* — only the `SAINSBURYS_SPEC` instance. Verifies legacy-GTIN routing, no-GTIN fuzzy fallback, units→cases ceiling (5 tests). |
| `tests/mcp_server/` | MCP tool surface against a faked ERP client. Smoke-confirms the wrapping is wired up (3 tests). |

The test suite runs fully offline. ERP responses are replayed from `tests/erp/cassettes/`; the pipeline tests reuse the same cassettes for snapshot construction.

## Live-run evidence

**[`docs/live-run-results.md`](live-run-results.md)** — captured output from a real end-to-end run against the trial ERP. 7 drafts created (split across SHIP-TESCO-DAV chilled and SHIP-TESCO-RDG ambient by temperature band), idempotency confirmed on re-run, full draft inventory listed. Reproducible via:

```bash
uv run python scripts/live_draft_run.py
```

## Where the rigor lives

For reviewers wanting to see the design reasoning rather than just the code:

- **[`DECISIONS.md`](../DECISIONS.md)** — 11 chronological decisions, each with rule + alternatives + why. The single most important file for understanding *why* the system is shaped this way. D-001 (config-driven adapters), D-002 (Polars + DuckDB), D-009/D-010/D-011 (the math-derived locks for kernel / allocation / calibration) are the load-bearing ones.

- **[`docs/architecture/formalism.md`](architecture/formalism.md)** — LaTeX-rendered mathematical model. §3 (entity resolution as stratified bipartite matching with FS posteriors), §4 (demand alignment as change-of-basis with non-trivial null space), §5 (allocation as constrained LP with water-filling), §6 (FSM-DAG interlock), §8 (10 explicit pushbacks against the Gemini source where the math diverged from the project's needs).

- **[`primitives/CPG/`](../primitives/CPG/)** — conceptual treatment of the four CPG primitives (Entity Resolution, Demand Alignment, Allocation, Workflow). Cross-references the formalism.

- **[`raw_truth.md`](../raw_truth.md)** — append-only Gemini transcripts (iterations 1–9). Useful for understanding *what we were told* before the formalism doc says how we *adapted* it.

- **[`working-doc.md`](../working-doc.md)** — operating index linking everything else; locked-decisions table; open questions; data-driven gotchas with explicit fixture references.

## Re-recording cassettes

If the ERP API mock state changes:

```bash
uv run pytest tests/erp/ --record-mode=once
```

The bearer token is scrubbed automatically (`tests/conftest.py` filters the `Authorization` header). Re-runs after recording are offline — `record_mode` defaults to `none`.

## Non-goals (deliberate)

- Drift detection (formalism §9.2) — named, deferred.
- Retailer-depot-string → `ship_to_location_id` mapping — `create_drafts_for_safe_lines_tool` takes the ship-to id explicitly. The parallel adapter is acknowledged in `working-doc.md` Design gaps #3.
- Supervised Cascaded Classification calibrator — D-011 names the path; trial scope ships only the unsupervised Fellegi-Sunter posteriors.
- Production-grade DOW kernel learning — D-009 uses the static UK-grocery profile; the simplex-NNLS upgrade path is documented for ≥ ~26 weeks of EPOS.
