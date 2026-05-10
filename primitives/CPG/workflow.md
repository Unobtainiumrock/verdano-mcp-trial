# Workflow primitives — FSM, DAG, review queue, idempotency

The workflow layer combines two interlocking structures plus two cross-cutting concerns:

- **FSM** — finite-state machine for the lifecycle of business entities (specifically `OrderDraft`).
- **DAG** — directed acyclic graph for the compute pipeline that produces the data the FSM transitions depend on.
- **Review queue** — a partially-ordered set of unresolved decisions awaiting human input.
- **Idempotency** — a structural condition on side-effecting operations (notably draft creation).

This primitive integrates Gemini's "FSM vs DAG vs Markov" framing ([`raw_truth.md`](../../raw_truth.md) iteration 4 §"Workflow Math") and corrects the implicit-parallel framing into an **interlocking** one: FSM transition guards are *outputs* of the DAG.

## FSM — order-draft lifecycle

For each (retailer, SKU, week) tuple post-resolution, the system tracks state in:

$$
\mathcal{S} = \{\textit{New},\ \textit{Resolved},\ \textit{Classified},\ \textit{Drafted},\ \textit{Blocked},\ \textit{Reviewing}\}
$$

Transitions are guarded by boolean predicates on resolution and allocation outputs. See [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §6 for the transition relation in formal notation. Informally:

| From | To | Guard |
|---|---|---|
| `New` | `Resolved` | A mapping edge with $w \geq \theta_{\text{auto}}$ exists |
| `New` | `Reviewing` | No edge or $w < \theta_{\text{auto}}$ |
| `Resolved` | `Classified` | FTP computed |
| `Classified` | `Drafted` | Classification = `Safe` and operator opted-in to auto-draft |
| `Classified` | `Reviewing` | Classification = `At-risk` |
| `Reviewing` | `Resolved` | Operator confirmed mapping |
| `Reviewing` | `Blocked` | Operator declined / no mapping possible |

`Drafted` and `Blocked` are terminal in this FSM. Operator overrides can re-enter `Reviewing` from `Classified`.

This is **deterministic**, not stochastic. Markov-style transition probabilities don't apply here — the guards are functions of fully-observed inputs, not random variables. (See "Where Markov earns its keep" below for the cases where stochastic models *do* apply.)

## DAG — compute pipeline

Each invocation of `analyze_week_fulfillment` runs a fixed computation graph. Nodes:

```
load_retailer_csvs ─┐
                    ├─► resolve_mappings ─┐
load_erp_master ────┘                     │
                                          ├─► classify_lines ─► route_to_state
load_erp_inventory ──┐                    │
                     ├─► compute_ftp ─────┘
load_open_orders ────┘
```

The DAG enforces topological order — `compute_ftp` cannot run before its inventory and open-order inputs are loaded; `classify_lines` cannot run before `resolve_mappings` and `compute_ftp`. This is what makes coarse-grained MCP tools (per Gemini's MCP architecture advice and our intent) reasonable: the LLM doesn't orchestrate the DAG, it asks for an end-to-end result.

Nodes are pure functions of their inputs. There is no shared mutable state in the DAG. Side-effecting operations (draft creation) sit *outside* the DAG, downstream of state transitions.

## How the FSM and DAG interlock

This is the structural point Gemini's parallel framing missed:

> The DAG produces the values that FSM guards evaluate.

Concretely: the `Inventory ≥ Demand` guard on the `Classified → Drafted` transition is a comparison that requires both values to have been computed by the DAG. The FSM does not run until the DAG has produced its outputs. The FSM does not *re-compute* anything; it *reads* DAG outputs and applies guard predicates.

This means the runtime of an `analyze_week_fulfillment` call is:

1. Run the DAG (parallel where independent, topologically ordered where dependent).
2. For each (retailer, sku, week) tuple, evaluate the FSM transitions using DAG outputs.
3. Emit the per-tuple final state.

## Review queue — partially-ordered set under priority

The review queue is the union of all tuples in state `Reviewing`, ordered by:

1. **Priority** — `Blocked` mappings (no candidate) ahead of low-confidence mappings (candidate to verify).
2. **SLA** — `required_date` proximity. Reviewing items close to their delivery cutoff are surfaced first.
3. **Asymmetric value** — temperature-band-mismatch flags are pushed up regardless of SLA (high-precision "mapping is wrong" signal).

This is a partial order, not a total order — ties are operator-resolvable.

The review surface must satisfy the README's evaluation criterion (low-friction; obvious *why* a human was pinged; minimal context for intelligent action) — captured as a task in [`working-doc.md`](../../working-doc.md) Tasks #7.

## Idempotency — a structural condition on side-effecting ops

The single side-effecting operation is `POST /erp/order-drafts`. The ERP doc guarantees that a re-POST with the same `external_reference` returns the *existing* draft:

$$
\textit{create\_draft}(\textit{ref},\, \textit{payload}) \circ \textit{create\_draft}(\textit{ref},\, \textit{payload}) = \textit{create\_draft}(\textit{ref},\, \textit{payload})
$$

This is a clean **idempotent operation** (functionally — the operation composed with itself equals itself; cassette-confirmed in `tests/erp/test_client.py::test_create_order_draft_is_idempotent`).

We make the idempotency *load-bearing* by deriving `external_reference` deterministically from a hash of the upstream key. This makes the pipeline safe under retry: a failed pipeline run can be re-run end-to-end without producing duplicate drafts. See [`allocation.md`](allocation.md) for the formula.

## Where Markov earns its keep (the pushback against full Gemini-discard)

Gemini said "discard Markov chains" because workflow transitions are deterministic. That's correct *for the workflow FSM*. It's incorrect *for forecast drift detection*:

- The relationship between published forecast and observed EPOS is intrinsically noisy.
- Forecast residuals are a stochastic signal.
- Drift-vs-no-drift is a signal-detection problem with an explicit threshold.

If we add drift detection (mentioned as optional in the README and as a deferred concern in [`working-doc.md`](../../working-doc.md) Design notes), Markov-style or signal-detection-style models become appropriate *there*. The full discard is too sweeping.

For this trial we don't ship drift detection, but we name the modeling space so it doesn't get discarded by inheritance.

## Cross-references

- Formal treatment: [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §6, §7 (idempotency).
- Related design gap: idempotent order drafts, [`working-doc.md`](../../working-doc.md) Design gaps vs README evaluation criteria #5.
- Cassette-confirmed idempotency test: `tests/erp/test_client.py::test_create_order_draft_is_idempotent`.
- Decisions: D-006 (workflow modeling = FSM + DAG; Markov reserved for drift).
