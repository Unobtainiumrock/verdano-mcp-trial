# ERP Data Primitives — the Information Layer

This file populates the **data** layer of the ERP-primitives ontology from [raw-truth.md](../../docs/process/raw-truth.md). Cross-references the canonical entity model in [docs/architecture/verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).

---

## (a) Abstract definition

> At its core, an ERP is a massive, highly structured database. It categorizes information into three fundamental types to maintain data integrity across the enterprise.
> *(— `raw-truth.md` §1)*

Three sub-primitives:

- **Master Data** — core entities of the business; changes infrequently; serves as the primary reference point across all modules.
- **Transactional Data** — records of daily business events; created constantly; **always references Master Data**.
- **Metadata (Configuration Data)** — the rules and parameters that govern how the ERP operates.

---

## (b) Trial-specific instantiation

### Master Data — Verdano

These come from the ERP API's read-only master endpoints; we never write canonical master state.

| Master entity | ERP API endpoint | Notable fields | Adapter relevance |
|---|---|---|---|
| `ERPProduct` | `GET /erp/products` | `sku`, `name`, `case_pack`, `current_gtins`, `legacy_gtins`, `aliases`, `temperature_band` | Mapping resolver fall-through path: `current_gtins → legacy_gtins → aliases → fuzzy name`. `case_pack` resolves the units↔cases conversion. `temperature_band` cross-checks retailer-declared band as a confidence signal. |
| `Customer` (`sold_to` / `bill_to` / `ship_to`) | `GET /erp/customers` | hierarchy | `ship_to_location_id` is required for `POST /erp/order-drafts`; depot-string → `ship_to_location_id` is its own mapping problem (parallel to product mapping). |
| `Warehouse` | `GET /erp/warehouses` | `warehouse_id`, `temperature_band` | Free-to-promise sums available cases by *temperature-compatible* warehouse, not just by SKU. |

Master data is **read** from the ERP and held in-memory for the duration of each pipeline run. Local persistence is available via `DuckDBRepository` (D-025) — mapping cache, review labels, audit log, and residual history are stored across sessions when `VERDANO_STORAGE_BACKEND=duckdb`. See [storage-runtime-decision.md](../../docs/architecture/storage-runtime-decision.md) and [`docs/usage.md`](../../docs/usage.md). We do not author master records.

### Transactional Data — Verdano

These also come from the ERP, plus a write path for our own draft creation.

| Transactional entity | ERP API endpoint | Notes |
|---|---|---|
| `OpenSalesOrder` (with lines) | `GET /erp/open-orders` (filterable by `retailer`, `sku`) | Already-committed demand. Subtracted from `available_cases` in the FTP formula. |
| `OrderDraft` (with lines) | `POST /erp/order-drafts`, `GET /erp/order-drafts` | The single transactional entity *we* author. Idempotent via deterministic `external_reference`. |
| Inventory movements (implicit) | reflected in `GET /erp/inventory` | We don't see individual movements; we see the resulting `available_cases` and `allocated_cases` per (sku, warehouse). |

The retailer-side facts (`ForecastDemandLine`, `EPOSActualLine`) are technically *transactional from the retailer's perspective* but live outside the ERP's data domain — they enter the system through adapters from CSVs.

### Metadata / Configuration — Verdano

The configuration layer is where the system's own metadata lives. None of this is owned by the ERP API; it's owned by our project.

- **Retailer adapter specs** (one per retailer; Pydantic `RetailerSpec`). Per D-001. Each spec declares column mappings, parsing rules (date format, week convention, unit semantics), default fan-out policy for aggregated geography (`"All Depots"`), default temperature-band declaration handling.
- **Mapping policy** — fall-through order, fuzzy-match thresholds, confidence-weighting rules, temperature-band-mismatch penalty.
- **FTP window definitions** — what counts as "next week" (calendar week vs. ISO week vs. retailer-specific receipt week), and how a daily forecast (Tesco) rolls up to weekly.
- **Idempotency policy** — deterministic `external_reference` formula (e.g., `sha256(retailer | erp_sku | iso_week | ship_to_location_id)`).
- **Temperature-band compatibility rules** — chilled product → chilled warehouse, ambient → ambient. Cross-band routing requires explicit override.

Metadata is versioned with the codebase and treated as part of the project's source-of-truth, not as runtime state.

---

## Cross-references

- Canonical entity model: [verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).
- ERP API endpoints: [ERP API.md](../../docs/reference/erp-api.md).
- Storage / runtime: [storage-runtime-decision.md](../../docs/architecture/storage-runtime-decision.md).
- Decisions referenced: D-001 (adapter shape), D-002 (storage), D-004 (primitives backbone). See [DECISIONS.md](../../DECISIONS.md).
