# CPG primitives — the reconciliation layer

This directory documents the primitives of the **CPG (Consumer Packaged Goods) integration layer** — the layer that sits *between* retailers and the ERP and reconciles their incompatible representations of the same products, locations, dates, and quantities.

## Why CPG primitives don't mirror the ERP four-layer ontology

The ERP-side ontology (Data / Architectural / Process / Functional) describes a *system of record*. The CPG layer is a *reconciliation layer*, not a system of record. Forcing it into the same four-layer split produces awkward correspondences:

- "Architectural primitives" in CPG terms is mostly **defining absences** relative to ERP (no shared database, no shared primary key, no GL).
- "Functional primitives" has no real CPG analog — there's no AP/AR/HCM/Supply-Chain module split because we don't have user-facing modules.

Instead, the CPG primitives are decomposed by **the actual mathematical structure of the reconciliation problem**, surfaced in [`raw-truth.md`](../../docs/process/raw-truth.md) iteration 4:

| Primitive | What it captures | File |
|---|---|---|
| **Entity Resolution** | Mapping retailer SKUs / depots / dates to ERP equivalents under partial information | [`entity-resolution.md`](entity-resolution.md) |
| **Demand Alignment** | Reconciling incompatible *bases* — daily vs ISO-week, depot-named vs aggregated, cases vs consumer units | [`demand-alignment.md`](demand-alignment.md) |
| **Allocation** | Free-to-promise computation under temperature/warehouse compatibility, with supply-constrained policy | [`allocation.md`](allocation.md) |
| **Workflow** | FSM for entity lifecycle, DAG for compute pipeline, review queue, idempotency | [`workflow.md`](workflow.md) |

## Relationship to the formalism doc

These four files are the **conceptual / ontological** treatment. The **mathematical** treatment — LaTeX statements, formal definitions, theorem-style claims — lives in [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md). Each file here cross-references the relevant formalism section.

This split is deliberate: the ontology is expected to stabilize quickly while the formalism iterates. Decoupling them lets each evolve at its own pace.

## Sources

These files derive from [`raw-truth.md`](../../docs/process/raw-truth.md) iteration 4 (the Verdano-trial scope realignment) plus extensions added during integration where the Gemini source under-specified the problem. Divergences from the source are flagged inline and consolidated in [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §"Where this diverges from the Gemini source, and why".

## What this directory deliberately does *not* contain

- ERP-internal mechanics — see [`primitives/ERP/`](../ERP/).
- Decisions or rationale — see [`DECISIONS.md`](../../DECISIONS.md).
- Implementation guidance — that lives in `src/verdano/` once we re-engage the build phase.
