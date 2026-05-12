# ERP primitives — grounding context (out of operational scope)

> **Read this first.**
>
> Per **D-005** in [`DECISIONS.md`](../../DECISIONS.md), the ERP-internal primitives documented here are **grounding context, not operational scope** for the Verdano work-trial.
>
> The trial treats the ERP as an **external state machine accessed via HTTP API**. We do not implement, simulate, or reason about ERP-internal mechanics (General Ledger postings, RBAC enforcement, valuation matrices, referential-integrity constraints). Those are the ERP's job and they're handled behind the API boundary.
>
> The files in this directory exist so the system has *awareness* of how an ERP is built — it sharpens our understanding of the boundary we sit on, and informs how we model the API as an oracle.

The CPG-side primitives — bipartite mapping, demand alignment, allocation constraints, workflow primitives — are where this trial's mathematical work actually lives. See [`primitives/CPG/`](../CPG/) and [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md).

## Files in this directory

| File | What it documents | Operational relevance |
|---|---|---|
| [`data-primitives.md`](data-primitives.md) | Master / Transactional / Metadata data layers in ERP terms | Grounds the API's response shapes; informs adapter design at the boundary. |
| [`architectural-primitives.md`](architectural-primitives.md) | Single shared DB, RBAC, GL Engine | The "single shared DB" framing explains why the ERP is the canonical truth; RBAC and GL are out of scope. |
| [`process-primitives.md`](process-primitives.md) | P2P / O2C / R2R workflow cycles | Locates the trial at the front of O2C (Sales Order → Inventory Allocation). |
| [`functional-primitives.md`](functional-primitives.md) | Financials / HCM / Supply Chain modules | Locates the trial inside Supply Chain / Materials Management; everything else is out of scope. |

## Source

These files derive from [`raw-truth.md`](../../docs/process/raw-truth.md) iterations 1–3 (the Gemini conversation establishing the ERP-primitives ontology). The mathematical framing of those primitives (linear algebra, set theory) is preserved in `raw-truth.md` but **not** elevated into operational scope here.

## What this directory deliberately does *not* contain

- Implementation guidance for the MCP server.
- Mathematical models we operate on.
- Decisions about adapter design, mapping logic, FTP math, or workflow.

Those live in [`primitives/CPG/`](../CPG/), [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md), [`DECISIONS.md`](../../DECISIONS.md), and [`docs/architecture/cpg-reconciler-problem-entity-model.md`](../../docs/architecture/cpg-reconciler-problem-entity-model.md).
