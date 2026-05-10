# Storage / runtime decision — Polars + DuckDB

**Decision:** Logged as **D-002** in [DECISIONS.md](../../DECISIONS.md). Status: locked.

This document records the rationale for committing to **Polars** (compute) plus **DuckDB** (persistence) as the data substrate for the Verdano MCP work-trial.

> **Trial status:** Polars is fully operational as the compute engine. DuckDB is wired as a dependency and configurable via `VERDANO_DUCKDB_PATH` in [`config.py`](../../src/verdano/config.py), but **persistence tables are not yet implemented** — the trial pipeline operates entirely in-memory per HTTP-fetched ERP state. DuckDB cache/audit tables are a **phase-2 production target**. See the [Trial scope vs production roadmap](../usage.md#trial-scope-vs-production-roadmap) table in `docs/usage.md`.

## Stack

- **Compute:** [Polars](https://pola.rs/) ≥ 1.0. LazyFrames where possible. Eager `DataFrame` only at I/O boundaries.
- **Persistence:** [DuckDB](https://duckdb.org/) as a file-backed columnar SQL engine. Single `.duckdb` file under the project (gitignored).
- **Interop:** native — `pl.read_database`, `pl.DataFrame.write_database`, and DuckDB-side `from <polars_df>` / `duckdb.from_df`. No bridging code required.

## What lives where

| Data | Lives in | Source | Refresh |
|---|---|---|---|
| ERP master (products, customers, warehouses) | DuckDB cache table | `GET /erp/*` | on-demand or scheduled |
| ERP transactional (inventory, open orders) | DuckDB cache table | `GET /erp/inventory`, `GET /erp/open-orders` | per run |
| Retailer forecast / EPOS | DuckDB analytical table | CSV via Polars `read_csv` | per run |
| Retailer adapter specs | repo (YAML/Pydantic) | code | versioned with git |
| Mappings (retailer key → ERP sku) | DuckDB table (with confidence + evidence) | resolver output | regenerated per run; persisted for audit |

DuckDB is treated as a **cache and audit store**, not a parallel source-of-truth. The ERP API remains canonical (per [architectural-primitives.md](../../primitives/ERP/architectural-primitives.md)).

## Why this stack

**Why Polars over pandas.** Typed columns by default, lazy evaluation with a real query optimizer, ~10× memory and speed wins on the kinds of joins/aggregations this trial requires, and a more modern API surface. Within an 8-hour trial these gains are not load-bearing, but the resulting code reads more declaratively (and that's what reviewers see).

**Why DuckDB over Postgres / SQLite.** Postgres is more production-typical for transactional row-stores, but adding a Docker-Postgres dependency to an 8-hour trial is overhead without commensurate gain — the trial's data shape is analytical (column scans, aggregations across joins), which is where DuckDB's columnar engine excels. SQLite is row-oriented and would force us back into pandas-style reasoning. DuckDB gives us a real SQL contract that *also* matches the access pattern.

**Why not in-memory only.** Per the user's directive, production realism is a constraint. A pure-in-memory pipeline cannot demonstrate persistence, query inspection, schema migration, or audit replay. DuckDB-as-file restores those properties at near-zero setup cost.

## Migration path (what this *doesn't* lock us into)

If scale or governance demands move us off DuckDB onto Postgres:

1. Replace DuckDB connection with `psycopg` + `SQLAlchemy Core`.
2. Polars LazyFrames continue to drive compute via `pl.read_database` / `pl.write_database` against Postgres.
3. No compute rewrite. Adapter specs unchanged. Tests unchanged (cassettes are HTTP-level, not DB-level).

This optionality is the main reason DuckDB beat "in-memory only" — the file-backed SQL engine acts as the abstraction that makes the migration mechanical.

## What we explicitly do *not* commit to

- **No ORM.** Pydantic models for HTTP I/O; raw SQL or Polars expressions for the DB. Avoid the SQLAlchemy ORM-layer overhead inside this trial. (`SQLAlchemy Core` is fine if we ever migrate to Postgres.)
- **No dbt** in the trial. The transformations are small and fit naturally in Polars expressions; dbt's value (lineage, materialized models, test packs) doesn't pay back at this scale.
- **No Redis / no message bus.** No identified hot path; no event-stream driver. (Per [working-doc.md](../process/working-doc.md) Process / scope, the speculative tooling list is deferred.)

## Dev-experience notes

- The DuckDB file path is configurable via `VERDANO_DUCKDB_PATH` (default: `./.local/verdano.duckdb`).
- Add `.local/` and `*.duckdb` to `.gitignore` when the project skeleton lands (Step 6 of the active plan).
- For interactive inspection: `duckdb ./.local/verdano.duckdb` (CLI), or `pl.read_database("SELECT * FROM ...", con)` from a notebook.

## Cross-references

- Decision record: [DECISIONS.md](../../DECISIONS.md) §D-002.
- Architectural framing: [primitives/ERP/architectural-primitives.md](../../primitives/ERP/architectural-primitives.md).
- Working doc: [working-doc.md](../process/working-doc.md).
