# ERP Process Primitives — the Workflow Layer

This file populates the **process** layer of the ERP-primitives ontology from [raw-truth.md](../../docs/process/raw-truth.md). Cross-references the canonical entity model in [docs/architecture/verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).

---

## (a) Abstract definition

> Instead of looking at isolated departments, ERPs are built around standardized, cross-functional processes that chain transactional data together.
> *(— `raw-truth.md` §3)*

Three sub-primitives (the canonical "three cycles"):

- **Procure-to-Pay (P2P)** — Purchase Requisition → Purchase Order → Goods Receipt → Invoice Processing → Payment.
- **Order-to-Cash (O2C)** — Sales Order → Inventory Allocation → Shipping → Invoicing → Payment Collection.
- **Record-to-Report (R2R)** — Logging Transactions → Period Close → Consolidation → Financial Statements.

---

## (b) Trial-specific instantiation

### O2C — the only in-scope process primitive

The Verdano trial sits at the **front of the O2C chain**, between Sales Order and Inventory Allocation. We do not see the rest of the chain (shipping, invoicing, payment).

```
Retailer forecast       Sales Order draft       Inventory Allocation        Shipping       Invoicing       Payment
        │                    (we author)              (ERP commits)                                       
        ▼                         ▼                         ▼                    ▼              ▼            ▼
  ForecastDemandLine  ──────►  OrderDraft  ─[promote]─►  OpenSalesOrder  ────► out of scope ────────────────►
  EPOSActualLine                                              ▲
                                                              │
                                              consumes available_cases
                                              and emits allocated_cases
                                                              ▲
                                                              │
                                                       InventoryPosition
```

What our MCP tools answer is the question that gates the *first* step in this chain:

> **"Given the retailer-published forecast for next week, can the ERP fulfill it?"**

That decomposes into:

1. **Resolve** retailer forecast lines to ERP `sku`s (mapping resolver).
2. **Compute** free-to-promise per SKU per temperature-compatible warehouse (FTP math).
3. **Subtract** committed open-order demand for the same SKU within the window.
4. **Classify** each forecast line as **safe / at-risk / needs-review**.
5. **Optionally**, draft order(s) for the safe lines via `POST /erp/order-drafts`.

We never *commit* sales orders. The ERP's own commit step (drafts → real `OpenSalesOrder` records) happens behind a promotion path that this trial does not expose.

### P2P — out of scope

Verdano's procurement of raw material from upstream suppliers is upstream of every entity we touch. We assume products exist and inventory exists. The mock ERP does not expose Purchase Orders, Goods Receipts, or supplier invoices.

### R2R — out of scope

Period-close, consolidation, and financial reporting are downstream of every entity we touch. We do not model GL journal entries (see [architectural-primitives.md](architectural-primitives.md) — GL Engine out of scope) and therefore we cannot participate in R2R.

---

## Process-primitive implications for adapter design

Mapping the O2C entrypoint to the [canonical entity model](../../docs/architecture/verdano-problem-entity-model.md):

| O2C step | Canonical entity | What we do |
|---|---|---|
| Sales Order origination | `ForecastDemandLine` (CPG-side input) | Adapter normalizes per-retailer CSVs into canonical demand. |
| Sales Order resolution | `RetailerToErpMapping` | Mapping resolver fall-through (`current_gtins → legacy_gtins → aliases → fuzzy name`). |
| Inventory Allocation feasibility | `InventoryPosition` + `OpenSalesOrder` | FTP formula: `available_cases − allocated_cases − Σ open_order_cases(window)`. |
| Sales Order draft authoring | `OrderDraft` | Idempotent via deterministic `external_reference`. |

The "compare next week" output is essentially an **O2C feasibility report** before any draft is created. The optional draft creation is the single ERP-side mutation we ever perform.

---

## Cross-references

- Canonical entity model: [verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).
- Architectural layer: [architectural-primitives.md](architectural-primitives.md).
- ERP API endpoints: [ERP API.md](../../docs/reference/erp-api.md).
- Decisions referenced: D-001 (adapter shape), D-004 (primitives backbone). See [DECISIONS.md](../../DECISIONS.md).
