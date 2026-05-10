# ERP Functional Primitives — the Application Modules

This file populates the **functional** layer of the ERP-primitives ontology from [raw_truth.md](../../raw_truth.md). Cross-references the canonical entity model in [docs/architecture/verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).

---

## (a) Abstract definition

> These are the user-facing pillars that interact with the underlying database and workflows. At a minimum, a true ERP requires:
> *(— `raw_truth.md` §4)*

Three sub-primitives:

- **Financials / Accounting** — managing the ledger, accounts payable (AP), accounts receivable (AR), fixed assets.
- **Human Capital Management (HCM)** — managing the employee lifecycle, payroll, timesheets.
- **Supply Chain / Materials Management** — tracking inventory levels, warehouse management, procurement logic.

---

## (b) Trial-specific instantiation

### Supply Chain / Materials Management — the only in-scope functional primitive

This is the module the entire trial sits inside.

**Inventory tracking.** The mock ERP exposes a per-(SKU, warehouse) inventory position with two relevant fields:

- `available_cases` — uncommitted, sellable inventory.
- `allocated_cases` — already promised against existing demand (typically `OpenSalesOrder`s).

These are the inputs to the free-to-promise (FTP) calculation:

```
ftp_cases(sku, warehouses_compatible, window)
  = Σ_{w ∈ warehouses_compatible}  available_cases(sku, w)
  − Σ_{w ∈ warehouses_compatible}  allocated_cases(sku, w)
  − Σ_{o ∈ open_orders(retailer, sku, window)}  o.quantity_cases
```

The `warehouses_compatible` set is restricted by **temperature band** — chilled SKUs must ship from chilled warehouses, ambient from ambient.

**Warehouse management.** `GET /erp/warehouses` returns each warehouse's `temperature_band`. The mock ERP enforces band compatibility on `POST /erp/order-drafts` — attempting to ship a chilled SKU to an ambient warehouse fails validation. Our planning logic must enforce the same rule *before* attempting a draft.

**Procurement logic — out of scope.** Verdano's procurement of raw materials and finished goods is upstream of everything we see; the ERP API does not expose Purchase Orders. (See [process-primitives.md](process-primitives.md) — P2P out of scope.)

### Financials / Accounting — out of scope

Every order draft eventually flows into AR (Accounts Receivable) once invoiced, but invoicing happens after promotion to a real Sales Order, which is downstream of this trial. We do not model:

- The chart of accounts.
- AR / AP postings.
- Revenue recognition or COGS journal entries.
- Currency conversion (the ERP and retailer CSVs are both GBP).

### HCM — out of scope

The trial has no employee, payroll, or timesheet dimension. Worth noting only because the canonical primitives ontology requires acknowledging it; this module has zero presence in our system.

---

## Module boundaries — what this means for our code

The MCP server we build is, in ERP terms, a **decision-support tool around the front edge of Supply Chain / Materials Management**. It:

- Reads master data (Products, Customers, Warehouses) — purely Supply Chain reads.
- Reads transactional state (Inventory, Open Orders) — Supply Chain transactional reads.
- Authors a single transactional artifact (Order Drafts) — Supply Chain → O2C handoff.
- Crosses no module boundary into Financials, HCM, P2P, or R2R.

This narrowness is a feature, not a limitation. It maps directly to the README's evaluation criteria — extensibility *within* Supply Chain (more retailers, more SKUs) matters, while extensibility *across modules* is out of scope.

---

## Cross-references

- Canonical entity model: [verdano-problem-entity-model.md](../../docs/architecture/verdano-problem-entity-model.md).
- Process layer (O2C scope): [process-primitives.md](process-primitives.md).
- Architectural layer (DB / RBAC / GL): [architectural-primitives.md](architectural-primitives.md).
- Data layer (master / transactional / metadata): [data-primitives.md](data-primitives.md).
- Decisions referenced: D-001, D-002, D-004. See [DECISIONS.md](../../DECISIONS.md).
