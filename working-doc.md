# Verdano work-trial — working doc

This document is the **operating index**, not the authority. Authoritative content lives in the source-of-truth references below; this doc is a quick-scan workspace for active questions, tasks, gotchas, and design gaps.

## Source-of-truth references

- **Gemini conversation transcripts (append-only):** [`raw_truth.md`](raw_truth.md). User iterates with Gemini; new sections append at the bottom.
- **ERP primitives (grounding context, not operational scope per D-005):** [`primitives/ERP/README.md`](primitives/ERP/README.md) + the four primitive files. Documents how an ERP is built; we treat the actual ERP as an external state machine over HTTP.
- **CPG primitives (operational scope):** [`primitives/CPG/README.md`](primitives/CPG/README.md), [`entity-resolution.md`](primitives/CPG/entity-resolution.md), [`demand-alignment.md`](primitives/CPG/demand-alignment.md), [`allocation.md`](primitives/CPG/allocation.md), [`workflow.md`](primitives/CPG/workflow.md).
- **Mathematical formalism (LaTeX):** [`docs/architecture/formalism.md`](docs/architecture/formalism.md). Co-created from the Gemini source; explicit pushback section captures divergences.
- **Entity/relationship model:** [`docs/architecture/verdano-problem-entity-model.md`](docs/architecture/verdano-problem-entity-model.md).
- **Storage / runtime decision:** [`docs/architecture/storage-runtime-decision.md`](docs/architecture/storage-runtime-decision.md).
- **Decisions log:** [`DECISIONS.md`](DECISIONS.md) — chronological with rationale.
- **Trial brief:** [`README.md`](README.md), [`ERP API.md`](ERP%20API.md).
- **Reviewer's usage guide:** [`docs/usage.md`](docs/usage.md) — install, test, demo, MCP wiring.

`MATH-SOT` in Priority Forge is now `in_progress` (iteration #1 integrated). Further iterations expected as the user continues the Gemini conversation; the formalism doc is the primary destination for new mathematical content.

## Locked decisions

Each entry below points at its full decision record in [`DECISIONS.md`](DECISIONS.md).

| ID | Status | Rule (one-line) |
|---|---|---|
| **D-001** | locked | Adapter shape = config-driven spec + small pluggable resolver. Per-retailer subclasses fail the README's 2 → 200-customer scaling criterion. |
| **D-002** | locked | Storage / runtime = Polars (compute) + DuckDB (persistence). Real SQL contract, file-backed, native Polars interop, painless migration to Postgres if needed. |
| **D-003** | provisional | Canonical entities polymorphic with `confidence: float`. Tentative resolution under formalism §2: morphism formalism is independent of implementation; Pydantic-class polymorphism is a fine concrete realization of morphism domains/codomains. Final commit deferred to canonical-entities planning round. |
| **D-004** | locked | ERP primitives (`raw_truth.md`) are the ontological backbone. CPG primitives populated from MATH-SOT iteration #1 ([`primitives/CPG/`](primitives/CPG/)); further iterations expected. |
| **D-005** | locked | ERP-internal mathematics is out of operational scope. The trial treats the ERP as an external state machine over HTTP. `primitives/ERP/*` is grounding context, not implementation guidance. |
| **D-006** | locked | Workflow modelling = FSM (deterministic order-draft lifecycle) + DAG (compute pipeline), interlocked: FSM guards consume DAG outputs. Markov reserved for forecast-drift detection, not discarded wholesale. |
| **D-007** | locked | Demand alignment is a change-of-basis problem. Aggregation is total-preserving; disaggregation is policy-driven (`K`-kernel) and lossy. Inferred values carry provenance. |
| **D-008** | locked | CPG primitives decompose by problem structure (Entity Resolution / Demand Alignment / Allocation / Workflow), not a four-layer mirror of ERP. |
| **D-009** | locked | Disaggregation kernel: static UK-grocery DOW profile `[0.10, 0.10, 0.10, 0.15, 0.25, 0.20, 0.10]` as trial default. Uniform `1/7` is operationally dangerous and rejected. Production upgrade: simplex-constrained NNLS + Laplacian smoothing at ≥ ~26 weeks of EPOS. |
| **D-010** | locked | Allocation under supply scarcity: pro-rata default; water-filling for weighted (closed-form `ρd/Σ` is unsafe); fill-rate thresholding tripwire with config `τ_safe` (default 0.90). |
| **D-011** | locked | Confidence calibration: Fellegi-Sunter unsupervised posteriors for E_1/E_2/E_3 (locked via iteration 8) with priors ε=0.02, γ=0.10, α=1.5; Jaro-Winkler² for E_4 fuzzy; cascade is blocking-strategy not band-constraint (iteration 9); production calibrator is Cascaded Classification LR over [score, stratum-indicator, JW, TF-IDF, vertex_degree]; isotonic at N≥1000; beta as parallel optional refinement. |
| **D-012** | locked | Drift signal: lagged-actuals plausibility check (ratio f_{t+1}/max(a_t, 1) with thresholds [0.5, 1.5]). Promo-segmented (Tesco only; Sainsbury's has no flag column). NOT classical residual drift — fixture has no W19 forecast. Markov-style true drift reserved per D-006. |
| **D-013** | locked | Canonicalization: (1) size-unit regex normalizer in `_norm` — `kg→g`, `l→ml`, idempotent, symmetric on both sides; (2) new TF-IDF stratum E3b in the cascade between alias-exact (E3) and JW² fuzzy (E4), gated at τ_tfidf=0.5 with FS K_x penalty. Closes the lexical half of the size-aliasing gotcha; cleanly captures K_x=2 ambiguity on no-GTIN Falafel Bowl. |
| **D-014** | locked | Cascade-floor + dedup fixes (post-D-013 probe): (1) `MasterIndex` builds per-key SKU sets to prevent same-SKU K_x inflation (bug fix); (2) E4 minimum-confidence floor `e4_min_score=0.30` returns `Unmapped` instead of misleading low-confidence candidates; (3) E3b requires `tfidf_min_matched_tokens=2` shared tokens to fire — eliminates single-rare-token auto-allocations like `"VD"→Lentil Dal`. |

## Open questions

1. What is the most critical layer of importance in this process? The adapters, the sources, the normalized facts, or the decisions? Assumption: normalization and decisions are the bulk of the work.
2. "Mapped forecast to ERP SKU with sufficient confidence" — how is confidence defined / computed?
3. Is polymorphism the right call here, or is there a more straightforward way to do things that doesn't lead to overengineering?
   - **Status:** provisionally locked as D-003 with explicit hesitation preserved. Expected to re-examine under a linear-algebra / mapping-of-spaces framing once `primitives/CPG/` lands (tracked as `MATH-SOT`). Adapters may turn out to be better modeled as *morphisms between primitive spaces* than as OOP-polymorphic classes — the polymorphic Pydantic surface is load-bearing scaffolding, not a final commitment.
4. Should the hallucination-detection framework be included anywhere in the stack for grounded behavior?
5. ~~Is a relational DB the sound approach?~~ **Resolved by D-002:** Polars + DuckDB. DuckDB provides a real SQL contract (columnar OLAP); we get the relational benefits without the Postgres setup overhead. See [storage-runtime-decision.md](docs/architecture/storage-runtime-decision.md).
6. ~~Where do I get the API key?~~ **Resolved:** the trial brief includes it; copy from `README.md` into your `.env` as `VERDANO_ERP_API_KEY` (template in `.env.example`).

## Tasks

1. Determine the core characteristics that go into designing an adapter. These should be well-defined; strongly prefer to illustrate this in LaTeX-rendered math.
2. Define and enforce a good type system.
3. Create a robust mapping layer — look into Pydantic data classes etc.
4. Ground all components within the framework of primitives laid out by https://gemini.google.com/app/1fc794b42f25ae07.
5. Define canonical workflows.
6. Brief research phase on forecast mathematics. Infuse mathematical rigor at all layers: small theorems with proofs, flows defined as linear maps / spaces (linear algebra), relational algebras.
7. Determine the best mechanism for surfacing elements of the workflow to human review.
   - Low-friction: immediately actionable, obvious *why* a human was pinged, what actions they can take, and the minimal context needed to act intelligently.

## Data-driven gotchas (from fixture inspection)

Each item below corresponds to a deliberate test case in the mock CSVs. Treat each as a discrete action — the mapping/normalization/decision layers each need explicit handling for these.

1. **Legacy-GTIN fall-through.** `Berry Smoothie 250ml` has GTIN `5060000099999` (off-pattern from the `506000001xxxx` family); the matching Tesco row note reads *"retailer still uses old barcode internally"*. Pairs with the ERP's `legacy_gtins` field.
   - **Action:** mapping resolver fall-through order = `current_gtins → legacy_gtins → aliases → fuzzy name`. Surface which rung matched in the mapping evidence so confidence weight reflects it.

2. **Ambiguous-product fixtures (review-queue cases).**
   - Tesco: `T-9302 Falafel Bowl 350g` vs `T-9303 Falafel Bowl Large` (note: *"large pack but size omitted by retailer"*).
   - Sainsbury's: `Falafel Bowl 350g` row alongside a no-GTIN `Falafel Bowl` row — present in *both* the EPOS and forecast files.
   - **Action:** these are the canonical demos for the human-review surface. End-to-end test should drive each into the review queue with a self-explanatory reason and one-click resolution actions.

3. **Unit/size aliasing beyond cases-vs-eaches.** Sainsbury's `Tom Basil Soup 0.5kg` ↔ Tesco `Tomato Soup 500g` — different abbreviation **and** different size unit (`kg` vs `g`).
   - **Action:** normalization scope must include (a) size-unit conversion (`g`/`kg`/`ml`/`L`) and (b) name canonicalization (abbreviation expansion, stop-word stripping). Don't conflate this with case-pack conversion — it's a separate pass.

4. **Temperature band as a free mapping-validation signal.** Sainsbury's forecast carries `temperature_band` (`chilled`/`ambient`); ERP product master carries the same.
   - **Action:** add a cross-check in the confidence scorer — band mismatch between retailer-declared and mapped-ERP-product is a high-precision "mapping is wrong" signal. Cheap to wire, asymmetric value.

5. **Promo periods distort drift math.** Tesco forecast has `promo_flag` and notes (e.g. *"promo bay starting Monday"*, *"fixture expansion"*). EPOS-vs-forecast drift comparisons that ignore promo state will be noisy.
   - **Action:** segment drift comparisons by promo state; expose promo-vs-baseline forecast as separate signals. Sainsbury's has no promo_flag, so handle the asymmetry explicitly (default-false with a known-unknown caveat).

## Design gaps vs README evaluation criteria

The README names three eval criteria: code quality, abstraction quality, and articulation/tradeoffs. The items below are gaps where the current plan doesn't yet meet them.

1. **Decision log is itself a deliverable.** "Articulation & tradeoffs — log of decisions and judgements made, along with presentation" is one of three explicit eval criteria. Absent from tasks.
   - **Action:** allocate ~1 hour at the end for a `DECISIONS.md` (or similar) — a chronological log of choices, the alternatives considered, and *why*. Write entries as you go; a back-loaded one reads thin.

2. **"2 → 200 customers" biases against per-retailer subclasses.** README explicitly tests scaling of form factor. If polymorphism (open question #3) means "one `TescoAdapter` / `SainsburysAdapter` subclass each", the architecture fails the 200-retailer test by inspection.
   - **Action:** adapter = (column-mapping spec) + (parsing/normalization rules) + (small pluggable resolver). Polymorphism for the **core entity contracts** (`DemandLine`, `ActualsLine`, `ProductKey`); **configuration** for the per-retailer specifics. Onboarding retailer #3 should be a YAML/Pydantic spec, not a new file of imperative code.

3. **Customer-hierarchy mapping is a parallel adapter problem.** `POST /erp/order-drafts` requires `ship_to_location_id`. Tesco gives a depot string ("Daventry Chilled"); Sainsbury's gives `"All Depots"`.
   - **Action:** treat `retailer-depot-string → ship_to_location_id` as its own mapping (same `confidence + evidence + review queue` shape as the SKU mapping). For `"All Depots"`, define an explicit **fan-out / allocation policy** (e.g. proportional to historical EPOS by region, or default to a primary ship_to with a flag). Don't silently pick one.

4. **Free-to-promise math needs to be pinned down.** Inputs are listed (available, allocated, open orders) but the formula isn't.
   - **Action:** standardize on `ftp_cases(sku, window) = available_cases − allocated_cases − Σ open_order_cases(required_date ∈ window)`. Make the `window` and the **temperature-compatible warehouse set** explicit parameters. This formula is the line between "safe" and "at risk" — reviewers will look for it.

5. **Idempotent order drafts.** ERP doc: *"Reusing the same `external_reference` returns the existing draft."*
   - **Action:** derive `external_reference` deterministically — e.g. `sha256(retailer | erp_sku | iso_week | ship_to_location_id)`. Reruns and retries become safe by construction.

6. **Time-grain alignment is asymmetric and lossy.** Tesco = daily `delivery_date` (Mon–Sat). Sainsbury's = ISO-week aggregates with `geography="All Depots"`. You can roll Tesco *up* to a week trivially; you can't split Sainsbury's *down* to depot/day without an explicit policy.
   - **Action:** make the asymmetry explicit in the canonical demand model. The "compare next week" tool should declare its operating grain (week-level), and any depot/day claim derived from Sainsbury's must carry an `inferred=true` flag with the policy that produced it.

## Process / scope

1. **Tests.** Absent from tasks. README emphasizes code quality/extensibility.
   - **Action:** fixture-driven test suite — the four CSVs as inputs, recorded ERP responses via `vcrpy` or `responses`. Goal isn't coverage; it's demonstrating the adapter contract holds and the gotchas (above) actually route to the right outcomes.

2. **No OpenAPI page for the ERP** (per the doc).
   - **Action:** hand-roll a thin client — Pydantic response models + an `httpx.Client` wrapper, ~50 lines. Don't reach for a code generator.

3. **Out of scope for the trial — note but don't build.** The speculative tooling list (Kafka, Firehose, Grafana, Prometheus, bronze/silver/gold layered storage, Redis, full drift-detection system, LangGraph/LangChain orchestration) will read as unfocused if it shapes the deliverable. Mention in the decision log under "what we deliberately deferred" if useful; don't let it pull design weight now.

## Design notes / open considerations

- ~~**Relational vs not.**~~ Resolved by D-002 — Polars + DuckDB.
- **Hot/cold path split.** Probably no real hot path in scope. Skip Redis unless a concrete latency target appears.
- **Drift detection.** A simple EPOS-vs-prior-forecast residual with promo segmentation (per gotcha #5) is enough to demonstrate the *capability*. A full drift-detection system is out of scope.
