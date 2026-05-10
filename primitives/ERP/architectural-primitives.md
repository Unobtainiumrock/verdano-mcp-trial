# ERP Architectural Primitives — the System Layer

This file populates the **architectural** layer of the ERP-primitives ontology from [raw_truth.md](../../raw_truth.md). Cross-references the canonical entity model in [docs/architecture/verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).

---

## (a) Abstract definition

> The technical constraints that separate an ERP from a loose collection of disparate software tools.
> *(— `raw_truth.md` §2)*

Three sub-primitives:

- **The Single Shared Database** — all functional modules read from and write to the same centralized database schema. Eliminates data silos and reconciliation errors.
- **Role-Based Access Control (RBAC)** — strict authorization primitives ensuring Segregation of Duties (SoD).
- **The General Ledger (GL) Engine** — every operational movement is automatically translated into a financial debit or credit in the GL.

---

## (b) Trial-specific instantiation

### Single Shared Database — the ERP API as canonical boundary

For this trial, the "single shared database" primitive is realized by the **ERP HTTP API** (`erp.corvera.ai`). We do not own or replicate canonical state; the API is the single source of truth for products, customers, warehouses, inventory, and open orders.

- **What we read**: master data (`/erp/products`, `/erp/customers`, `/erp/warehouses`) and transactional state (`/erp/inventory`, `/erp/open-orders`).
- **What we write**: only `OrderDraft`s via `POST /erp/order-drafts`. No master mutation. No direct inventory mutation.
- **Local persistence (DuckDB) is a *cache*, not a parallel source-of-truth.** Per D-002, cached ERP master tables let us run offline tests and avoid hammering the live API during development. Retailer-side facts (forecast/EPOS CSVs) materialize into the same DuckDB but are *not* canonical ERP state — they're our own analytical inputs.
- **Reconciliation discipline.** When cached state and live state disagree, live state wins. Our cache layer must be re-populatable from the ERP API at any time.

### RBAC — the trial API key as identity primitive

The ERP API uses bearer-token auth: `Authorization: Bearer <api_key>`.

- The **trial API key** (`VERDANO_ERP_API_KEY` in `.env`) is the only identity primitive available in this trial. There is no per-user identity, no SoD between agents.
- `GET /erp/order-drafts` returns drafts created with *this* API key — the key itself acts as the implicit principal. This is a thin RBAC story but it's the one the trial provides.
- **Out of scope** but worth noting: a full SoD model would require distinguishing the agent that *creates* a draft from the agent that *promotes* it to a real sales order. The trial does not expose draft promotion, so this is moot here.
- **Secrets handling.** The key lives in `.env`, which is git-ignored. We never log it; vcrpy cassettes scrub the `Authorization` header before commit.

### GL Engine — out of scope

Every ERP movement eventually translates to a GL entry, but this trial sits **upstream** of that machinery. We produce sales-order *drafts*; the trial's mock ERP does not expose downstream GL behavior. We don't model debits/credits, the chart of accounts, or period close.

What this means concretely:

- We do not need to reason about revenue recognition, COGS, or AR.
- We do not need to model currency conversion (the ERP returns GBP; retailer CSVs are GBP).
- If the system grows beyond the trial, the GL engine becomes the natural downstream consumer of the order drafts we generate — but it lives in a different service.

---

## Cross-references

- Canonical entity model: [verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).
- ERP API auth and endpoints: [ERP API.md](../../ERP%20API.md).
- `.env` and gitignore policy: [.gitignore](../../.gitignore).
- Decisions referenced: D-002 (storage cache, not source-of-truth), D-004 (primitives backbone). See [DECISIONS.md](../../DECISIONS.md).
