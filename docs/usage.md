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

# 3. Confirm everything is wired up (213 tests, fully offline — no .env needed).
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
    forecast_csv="data/tesco_forecast_week20.csv",
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
├── canonical/         entity contracts + runtime registries (RetailerCode, FulfillmentClass, Stratum, etc.)
├── adapters/          single Adapter class + RetailerSpec configs (Tesco, Sainsbury)
├── mapping/           cascade resolver (ordered handler chain), normalizer pipeline, depot resolver
├── allocation/        FTP math + Safe/AtRisk/AtRiskSevere/NeedsVerification/Blocked classifier
├── pipeline/          analyze_week_fulfillment DAG + draft-creation logic (drafts.py)
├── erp/               hand-rolled HTTP client + Pydantic response models
├── drift/             extensible drift analysis — strategy pattern (plausibility + residual modes)
├── llm/               provider-agnostic LLM client + llm_augmented stratum + post-cascade re-ranker (optional)
├── mcp_server/        FastMCP server exposing 4 tools
├── config.py          .env loader (pydantic-settings) — all thresholds + LLM config
└── logging.py         structlog setup

primitives/
├── ERP/               ontological grounding (out of scope for the build, kept for context)
└── CPG/               ontological core (in scope) — entity-resolution, demand-alignment, allocation, workflow

docs/
├── usage.md                               this file
├── live-run-results.md                    evidence from live ERP run
├── architecture/
│   ├── formalism.md                       LaTeX math: morphisms, FS posteriors, change-of-basis, water-filling, FSM/DAG
│   ├── verdano-problem-entity-model.md    ER diagram + flowcharts
│   └── storage-runtime-decision.md        Polars + DuckDB decision memo
├── reference/
│   └── erp-api.md                         mock ERP HTTP API contract
└── process/                               design process artifacts
    ├── working-doc.md                     operating index
    ├── raw-truth.md                       Gemini transcripts (1–9)
    ├── prompts-for-gemini.md              MATH-SOT prompts
    └── prompts.md                         early brainstorming

DECISIONS.md              chronological D-001..D-020 with rationale + alternatives

data/
├── tesco_forecast_week20.csv
├── tesco_epos_actuals_week19.csv
├── sainsburys_forecast_week20.csv
└── sainsburys_epos_actuals_week19.csv

scripts/
├── setup-mcp.sh          one-command MCP setup for Cursor + Claude Desktop
└── live_draft_run.py     exercise MCP tools against the live ERP
```

## Running the MCP server

### One-command setup (recommended)

The setup script installs dependencies, configures `.env`, injects MCP entries into both Cursor and Claude Desktop, and runs a health check:

```bash
./scripts/setup-mcp.sh
```

After the script finishes, restart Cursor / Claude Desktop to pick up the new configuration.

Verify the server is healthy at any time:

```bash
uv run verdano-mcp --health
```

### Manual configuration (alternative)

If you prefer to configure MCP manually, add the following entry to your host's config file:

- **Cursor**: `~/.cursor/mcp.json`
- **Claude Desktop (macOS)**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Claude Desktop (Linux)**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "verdano": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/challenge", "run", "verdano-mcp"],
      "env": {
        "VERDANO_PROJECT_ROOT": "/absolute/path/to/challenge"
      }
    }
  }
}
```

Replace `/absolute/path/to/challenge` with the actual path to this repository on your machine.

The server speaks stdio transport — it is launched by the MCP host automatically; you do not run it directly in a terminal.

### Tools exposed

| Tool | Purpose |
|---|---|
| `analyze_week_fulfillment_tool(retailer, iso_week)` | Compare retailer forecast vs ERP supply for a given ISO week. Returns Safe / AtRisk / AtRiskSevere / Blocked per line, with operator-readable reasoning. |
| `list_review_queue_tool(retailer, iso_week)` | Filter to only the lines requiring human review (Blocked + AtRiskSevere + low-confidence mappings). The operator's first surface. |
| `create_drafts_for_safe_lines_tool(retailer, iso_week, required_date, ship_to_location_id?)` | Create `OrderDraft`s for every Safe-classified line. `ship_to_location_id` is optional — if omitted, the depot resolver auto-resolves from the first forecast line's location label (substring + fuzzy match). Pre-filters cross-band SKUs (`skipped`), catches per-line ERP errors (`failed`). Idempotent via `external_reference = sha256(retailer, sku, week, ship_to)`. |
| `compare_actuals_vs_forecast_tool(retailer, iso_week_forecast, iso_week_actuals, mode?)` | **Drift analysis** with two modes (D-020): `"plausibility"` (default) for lagged-actuals ratio check (D-012), `"residual"` for classical signed-residual on same-period data. Plausibility computes `forecast_eaches / max(actuals_eaches, 1)` with promo segmentation. Residual computes `actuals − forecast` with configurable threshold. See [DECISIONS.md D-012, D-020](../DECISIONS.md). |

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
| `tests/allocation/test_ftp.py` | FTPCalculator unit tests — band filtering, open-order week filtering, `sold_to=None` conservative path, negative FTP clamping, unknown SKU (8 tests). |
| `tests/allocation/test_classifier.py` | Classifier unit tests — Safe, AtRisk, AtRiskSevere, NeedsVerification, Blocked, zero-demand, threshold boundaries, frozen band (10 tests). |
| `tests/mcp_server/` | MCP tool surface against a faked ERP client. Draft-tool validation errors, retailer + iso_week rejection, exact classification counts, zero-qty skip, live-cassette regression (13 tests). |
| `tests/drift/` | Drift analysis — plausibility (ratio, promo segmentation, MCP tool wiring), residual (synthetic fixtures, direction registry, analyzer dispatch), invalid-mode error path, backward compatibility (27 tests). |
| `tests/mapping/` | Cascade resolver, TF-IDF index, normalizer, depot resolver — stratified matching, collision handling, floor gating, Jaro-Winkler scoring, depot auto-resolution (46 tests). |
| `tests/test_negative.py` | Error paths — empty/malformed CSV, non-numeric quantities, float truncation, invalid drift thresholds, unknown retailer spec, registry validation (13 tests). |
| `tests/test_config.py` | Config resolution (`_find_env_file` paths) and `_validate_iso_week` edge cases (10 tests). |
| `tests/test_registries.py` | Runtime registries for FulfillmentClass, MappingState, Stratum, DriftClass — builtins, registration, idempotency, ordered insertion (11 tests). |
| `tests/test_llm.py` | LLM client protocol, factory, `llm_augmented` stratum handler (mocked), depot LLM fallback — confidence gating, JSON error handling (7 tests). |
| `tests/test_reranker.py` | LLM post-cascade re-ranker (D-019) — should_rerank gating, agree/disagree/low-conf/failure paths, integration flow (16 tests). |
| `tests/mapping/test_normalize_pipeline.py` | Composable NormalizationPipeline — individual steps, brand stripping, stop words, pipeline composition, backward compatibility (12 tests). |
| `tests/mapping/test_handler_chain.py` | Stratum handler chain — default registration, custom handler short-circuit, append, `gtin_current` preemption, config exposure (5 tests). |
| `tests/adapters/test_aggregation.py` | `_aggregate_to_weekly` unit tests — promo-flag OR-ing, note dedup/sort, quantity summing, grouping-key correctness (9 tests). |

The test suite runs fully offline. ERP responses are replayed from `tests/erp/cassettes/`; the pipeline tests reuse the same cassettes for snapshot construction.

## Live-run evidence

**[`docs/live-run-results.md`](live-run-results.md)** — captured output from a real end-to-end run against the trial ERP. 7 drafts created (split across SHIP-TESCO-DAV chilled and SHIP-TESCO-RDG ambient by temperature band), idempotency confirmed on re-run, full draft inventory listed. Reproducible via:

```bash
uv run python scripts/live_draft_run.py
```

## Where the rigor lives

For reviewers wanting to see the design reasoning rather than just the code:

- **[`DECISIONS.md`](../DECISIONS.md)** — 20 chronological decisions (D-001..D-020), each with rule + alternatives + why. The single most important file for understanding *why* the system is shaped this way. D-001 (config-driven adapters), D-002 (Polars + DuckDB), D-009/D-010/D-011 (the math-derived locks for kernel / allocation / calibration), D-016 (config externalization), D-017 (LLM integration layer), D-018 (semantic stratum naming), D-019 (LLM re-ranker), D-020 (drift extensibility refactor) are the load-bearing ones.

- **[`docs/architecture/formalism.md`](architecture/formalism.md)** — LaTeX-rendered mathematical model. §3 (entity resolution as stratified bipartite matching with FS posteriors), §4 (demand alignment as change-of-basis with non-trivial null space), §5 (allocation as constrained LP with water-filling), §6 (FSM-DAG interlock), §8 (11 explicit pushbacks against the Gemini source where the math diverged from the project's needs).

- **[`primitives/CPG/`](../primitives/CPG/)** — conceptual treatment of the four CPG primitives (Entity Resolution, Demand Alignment, Allocation, Workflow). Cross-references the formalism.

- **[`raw-truth.md`](process/raw-truth.md)** — append-only Gemini transcripts (iterations 1–9). Useful for understanding *what we were told* before the formalism doc says how we *adapted* it.

- **[`working-doc.md`](process/working-doc.md)** — operating index linking everything else; locked-decisions table; open questions; data-driven gotchas with explicit fixture references.

## Re-recording cassettes

If the ERP API mock state changes:

```bash
uv run pytest tests/erp/ --record-mode=once
```

The bearer token is scrubbed automatically (`tests/conftest.py` filters the `Authorization` header). Re-runs after recording are offline — `record_mode` defaults to `none`.

## Trial scope vs production roadmap

The trial ships a complete, tested end-to-end pipeline. Several capabilities were designed and documented but intentionally deferred because the trial fixture doesn't provide the data to exercise them. The table below consolidates all such items so reviewers can see the multi-phase story in one place.

| Item | Trial ships | Production upgrade | Decision ref |
|------|------------|-------------------|--------------|
| DuckDB persistence (cache + audit) | Dep wired, config ready, schema designed | Implement cache tables per D-002 memo | D-002 |
| DOW kernel consumption | Static profile on spec | Pipeline disaggregation using `dow_kernel` | D-009 |
| Simplex-NNLS learned kernel | Static config | At >= 26 weeks EPOS | D-009 |
| Supervised calibrator (Cascaded Classification LR) | Fellegi-Sunter + JW² unsupervised | At >= 200 labels | D-011 |
| Isotonic regression calibrator | n/a | At >= 1000 labels, replace LR-as-calibrator | D-011 |
| Classical residual drift | Implemented as `residual` mode in drift strategy pattern (D-020) | Activate via `mode="residual"` when same-period data available | D-006, D-012, D-020 |
| Markov drift detection | Reserved | Multi-week residual history | D-006 |
| Temperature-band confidence penalty | Documented, deferred | Pass band through RetailerProductKey | formalism §3.2 |
| Retailer-depot-string mapping | Depot resolver (substring + fuzzy + optional LLM fallback) | Implemented in `mapping/depot.py` | D-015, D-017 |
| Brand-prefix / stop-word normalization | Composable `NormalizationPipeline`; brand/stop-word steps available but not default | Activate via config or custom pipeline | D-013, D-017 |
| `RetailerCode` runtime extensibility | Registry-constrained `str` (implemented) | `register_retailer()` + `validate_retailer_code()` | D-015 |
| Config externalization | All thresholds in `Settings` with `VERDANO_` env prefix | Operator-tunable without code deploys | D-016 |
| LLM entity resolution (`llm_augmented` stratum) | Provider-agnostic client, `llm_augmented` handler, depot LLM fallback — all optional | Enable via `VERDANO_LLM_API_KEY` | D-017 |
| LLM post-cascade re-ranker | Validates low-confidence / ambiguous cascade matches via LLM second opinion (optional) | Tune via `VERDANO_RERANK_*` settings | D-019 |
| FulfillmentClass / Stratum / MappingState / DriftClass extensibility | Runtime registries (same pattern as RetailerCode) | `register_*()` functions | D-016 |

## Non-goals (deliberate)

- Markov-style true drift detection (formalism §9.2) — named, deferred. Classical residual drift is implemented as `mode="residual"` (D-020); Markov requires multi-week residual history.
- Retailer-depot-string → `ship_to_location_id` mapping — now auto-resolved by `mapping/depot.py` (substring + fuzzy). `create_drafts_for_safe_lines_tool` still accepts an explicit override.
- Supervised Cascaded Classification calibrator — D-011 names the path; trial scope ships only the unsupervised Fellegi-Sunter posteriors.
- Production-grade DOW kernel learning — D-009 uses the static UK-grocery profile; the simplex-NNLS upgrade path is documented for ≥ ~26 weeks of EPOS.
- Temperature-band confidence penalty — documented in formalism §3.2; deferred because the resolver doesn't have access to the retailer-side band at its call site. Production scope: pass band through `RetailerProductKey` or as a resolver parameter.
