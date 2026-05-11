# Decisions log — Verdano MCP work-trial

Chronological log of architectural and process decisions. New entries append at the bottom. Each entry: ID, date, the decision, alternatives considered, the *why*, and a status.

Status legend: **locked** (committed, not revisiting without cause), **provisional** (committed for now but explicitly revisitable), **open** (still being worked).

---

## D-001 — Adapter shape: config-driven spec + small pluggable resolver

**Date:** 2026-05-06
**Status:** locked

**Decision.** Each retailer is onboarded by writing a column-mapping spec (YAML or Pydantic config) plus parsing/normalization rules, not a new `RetailerAdapter` subclass. Polymorphism is reserved for the **core entity contracts** (`CanonicalDemandLine`, `CanonicalActualsLine`, `RetailerProductKey`, `MappingResult`); per-retailer specifics live in configuration.

**Alternatives.**

- One `Adapter` subclass per retailer (the textbook OOP move). Rejected: at 200 retailers this is 200 hand-written classes with mostly-duplicated parsing code and an explosion of class-level branches.
- Pure functional dispatch on retailer code. Rejected: scatters per-retailer logic across utility modules with no single declarative spec to read.

**Why.** The README's evaluation criteria explicitly include `"does your solution have a form factor that scales easily from 2 customers to 200 customers?"`. Subclass-per-retailer fails that criterion by inspection. Config-driven onboarding turns retailer #3 from a "write code" task into an "edit a spec file" task.

---

## D-002 — Storage / runtime: Polars + DuckDB

**Date:** 2026-05-06
**Status:** locked

**Decision.** Compute layer is **Polars** (LazyFrames where possible). Persistence is **DuckDB** as a file-backed columnar SQL engine. Native Polars ↔ DuckDB interop is used for materialization.

**Alternatives.**

- Polars-only, in-memory. Rejected: user explicitly flagged production-realism concern; nothing persists between runs; no SQL contract.
- pandas in-memory. Rejected: same realism gap, plus loses Polars's typed-column ergonomics and lazy optimizer.
- Postgres + SQLAlchemy (run locally via Docker). Rejected for *this* trial: heavier setup overhead inside an 8-hour window; ORM layer between us and the columnar story; can be migrated *to* later without rewriting compute.
- SQLite + SQLAlchemy. Rejected: row-store; less production-typical for analytical workloads than DuckDB.

**Why.** Polars + DuckDB satisfies the "production-realistic, real SQL engine, real persistence" constraint while keeping setup overhead near-zero (both are pip-installable, no daemon, no Docker). The migration path to Postgres is straightforward — swap DuckDB for `psycopg` + `SQLAlchemy Core` behind the same Polars-LazyFrame compute, no compute rewrite. Polars's lazy evaluation also gives a credible columnar query optimizer story for free.

---

## D-003 — Canonical entity contracts: provisionally polymorphic, `confidence: float`

**Date:** 2026-05-06
**Status:** provisional (re-examine after MATH-SOT lands)

**Decision.** Core entity contracts (`CanonicalDemandLine`, `CanonicalActualsLine`, `RetailerProductKey`, `MappingResult`) are modeled as Pydantic classes with the option of polymorphic refinement (e.g., `MappingResult.evidence` as a sum-type list). `MappingResult.confidence` is a `float` in `[0, 1]`.

**Alternatives.**

- Keep classical-OOP polymorphism throughout, including per-retailer subclass hierarchies. Already rejected by D-001.
- Encode confidence as a discrete enum (`high` / `medium` / `low`). Rejected: discards information needed for downstream thresholding and for any ML-friendly extension.

**Why.** The user has open hesitation about whether polymorphism is the right framing here. The system is expected to evolve toward a linear-algebra / mapping-of-spaces formalism (adapters as morphisms between primitive spaces, not class hierarchies). This decision is therefore deliberately marked **provisional** — load-bearing structure, but explicitly revisitable once MATH-SOT (the parallel formal-modeling work the user is iterating on with Gemini) produces a verdict.

---

## D-004 — ERP primitives (`raw-truth.md`) are the ontological backbone

**Date:** 2026-05-06
**Status:** locked

**Decision.** The four-layer ERP primitives ontology in `raw-truth.md` (Data / Architectural / Process / Functional) is the source of truth for the ERP-side concepts. The skeleton at `primitives/ERP/{data,architectural,process,functional}-primitives.md` is populated from `raw-truth.md` with trial-specific instantiation. The canonical entity model in `docs/architecture/verdano-problem-entity-model.md` cross-references these primitives.

**Alternatives.**

- Skip the primitives reframing; ground only in the existing entity model. Rejected: loses the ontological rigor the user asked for.
- Wait until CPG primitives are also ready before populating ERP. Rejected: ERP primitives are independently derivable from `raw-truth.md` *now*; CPG primitives are blocked on the user's Gemini iteration. Decoupling lets us make progress.

**Why.** Grounds adapters as mappings between two primitive spaces (CPG-side and ERP-side), which is the framing the user wants and which dovetails with the linear-algebra direction in MATH-SOT. CPG-side primitives are deferred; see MATH-SOT.

---

## D-005 — ERP-internal mathematics is out of operational scope

**Date:** 2026-05-06
**Status:** locked

**Decision.** The mathematical framing of the ERP's internal mechanics — General Ledger null-space (`1ᵀW = 0ᵀ`), valuation matrix `W`, referential-integrity inclusion dependencies, RBAC permission composition, Segregation-of-Duties negative constraints — is **not load-bearing** for the trial. The trial treats the ERP as an external state machine accessed via HTTP API. The `primitives/ERP/*.md` files are preserved as **grounding context**, not implementation guidance. A `primitives/ERP/README.md` makes this explicit at the directory level.

**Alternatives.**

- Drop the ERP primitives entirely. Rejected: the user explicitly wanted the ERP-layer awareness preserved, and it sharpens our understanding of the API boundary we sit on.
- Treat the ERP-internal math as in-scope and try to mirror it. Rejected: category error — we don't *implement* the ERP, we integrate against it. Confirmed in the Gemini scope-realignment exchange (raw-truth.md iteration 4).

**Why.** Keeps focus on the layer we actually build: integration, reconciliation, and agentic orchestration. Prevents the ERP-internal mathematical sketches from accidentally pulling design weight onto the wrong problem.

---

## D-006 — Workflow modelling: FSM + DAG (interlocked); Markov reserved for drift

**Date:** 2026-05-06
**Status:** locked

**Decision.** The order-draft lifecycle is modeled as a deterministic finite-state machine. The compute pipeline is modeled as a DAG of pure functions. The two interlock: **FSM transition guards consume DAG outputs**. Markov-chain models are **reserved for forecast-drift detection** if and when that capability is built — they are *not* discarded wholesale.

**Alternatives.**

- Discard Markov entirely (Gemini's recommendation). Rejected: too sweeping. Workflow is deterministic, but EPOS-vs-forecast drift is intrinsically a noisy-signal problem where Markov-style models earn their keep.
- Treat FSM and DAG as parallel independent structures (Gemini's parallel framing). Rejected: the FSM consumes DAG outputs; framing them as parallel hides the dependency.

**Why.** Captures the actual computational structure of `analyze_week_fulfillment`: first run the DAG (parallel where possible), then evaluate FSM transitions on a per-tuple basis using DAG outputs. Documented in `primitives/CPG/workflow.md` and `docs/architecture/formalism.md` §6.

---

## D-007 — Demand alignment is a change-of-basis problem, not a tensor reshape

**Date:** 2026-05-06
**Status:** locked

**Decision.** Tesco and Sainsbury's publish demand into **incompatible bases** (daily vs ISO-week, depot-named vs aggregated, cases vs consumer units). Aligning these is a sequence of explicit linear maps — aggregation operators `A` (total-preserving, lossless) and disaggregation kernels `K` (policy-driven, lossy). Every disaggregated value carries provenance (`inferred=true` plus a reference to the kernel that produced it).

**Alternatives.**

- Single tensor `D ∈ ℝ^{S × L × T}` (Gemini's framing). Rejected: hides the asymmetry that determines what claims the system can defensibly make. Sainsbury's "All Depots" can't be split to per-depot without committing to a kernel.
- Hand-wave time/location/unit alignment as "just normalize". Rejected: produces silently-wrong reconciliations on size-unit aliases (Tom Basil 0.5kg ↔ Tomato 500g).

**Why.** The lossy direction (disaggregation) is the load-bearing fact. Making it explicit forces the system to declare its operating grain (week-level for the comparison tool) and to surface inferred values transparently. Documented in `primitives/CPG/demand-alignment.md` and `docs/architecture/formalism.md` §4.

---

## D-008 — CPG primitives use a problem-shaped decomposition, not a four-layer mirror of ERP

**Date:** 2026-05-06
**Status:** locked

**Decision.** `primitives/CPG/` does **not** mirror the ERP four-layer split (Data / Architectural / Process / Functional). The CPG layer is a *reconciliation layer*, not a system of record; the four-layer split fits awkwardly. Instead, CPG primitives decompose by the actual mathematical structure of the reconciliation problem: **Entity Resolution**, **Demand Alignment**, **Allocation**, **Workflow** (with idempotency folded in).

**Alternatives.**

- Mirror the ERP four-layer split for symmetry. Rejected: "Architectural primitives" in CPG terms reduces mostly to absences relative to ERP; "Functional primitives" has no real CPG analog. The asymmetry is itself meaningful.
- Combine CPG primitives into a single document. Rejected: the four primitives are independently rich enough to warrant separate files; bundling buries the structure.

**Why.** Aligns the file structure with the mathematical structure surfaced in `docs/architecture/formalism.md`. Makes each primitive independently navigable and editable. The mismatch between ERP and CPG structures is *captured* (in `primitives/CPG/README.md`) rather than papered over.

---

## D-009 — Disaggregation kernel: static DOW profile default; simplex-NNLS upgrade path

**Date:** 2026-05-09
**Status:** locked
**Source:** Gemini iteration 6 (`raw-truth.md`).

**Decision.** Default disaggregation kernel for retailers with no historical EPOS is a **config-declared static day-of-week profile**:

$$K_{\text{default}} = [0.10,\ 0.10,\ 0.10,\ 0.15,\ 0.25,\ 0.20,\ 0.10]^T \quad (\text{Mon} \to \text{Sun})$$

This is "best-practice UK grocery DOW profile" — defensible without learning, infinitely better than uniform $1/7$. Per-retailer override allowed in the adapter spec (per **D-001**).

For production scope (≥ ~26 weeks of labeled per-day actuals), the upgrade path is **simplex-constrained NNLS with optional Laplacian smoothing**:

$$\min_{K} \|K D_{\text{weekly}} - D_{\text{actual}}\|_F^2 + \lambda \|L K\|_F^2 \quad\text{s.t.}\quad K \geq 0,\ \mathbf{1}^T K = \mathbf{1}^T$$

The constraint $\mathbf{1}^T K = \mathbf{1}^T$ ensures column-stochasticity, satisfying $A K = I_{|T_w|}$ exactly.

**Alternatives.**

- Uniform kernel $K = 1/7$. **Rejected** as operationally dangerous: triggers false stockouts early in the week, hides risk late in the week (grocery sales heavily skew Thu/Fri/Sat). Gemini surfaced this as a load-bearing operational point.
- Parameterized kernel $K(\theta;\,\text{covariates})$. Rejected at trial scale: identifiability collapses with small $N$. Per Gemini, week-of-year seasonality affects *weekly volume* not the *day-of-week distribution* anyway, so covariate-dependence isn't worth the complexity until multi-year data lands.

**Why.** Concrete defensible default for the trial; principled upgrade path that doesn't require rewriting the adapter contract.

**Captured in:** [`primitives/CPG/demand-alignment.md`](primitives/CPG/demand-alignment.md), [`docs/architecture/formalism.md`](docs/architecture/formalism.md) §4.

---

## D-010 — Allocation under supply scarcity: pro-rata default, water-filling for weighted, fill-rate tripwire pattern

**Date:** 2026-05-09
**Status:** locked
**Source:** Gemini iteration 7 (`raw-truth.md`).

**Decision.** Three components:

1. **Default objective:** **Pro-rata** allocation, $x_i = d_i \cdot \dfrac{s}{\sum_j d_j}$. Selected because (a) Verdano has no strict commercial-priority story, (b) pro-rata guarantees identical fill rates across retailers and is trivially explainable to buyers, (c) it requires no hyperparameters.

2. **Weighted-priority generalization:** **Water-filling algorithm**, *not* the closed-form $x_i = (\rho_i \cdot d_i) \cdot s / \sum_j (\rho_j \cdot d_j)$. The closed form can violate the upper-bound constraint $x_i \leq d_i$ when $\rho$ is skewed; water-filling preserves all constraints by allocating continuously and freezing each $x_i$ as it hits $d_i$, redistributing remaining supply.

3. **Auto-vs-human-review tripwire:** **Fill-rate thresholding** pattern. Define $\tau_{\text{safe}}$ such that:
   - $s / \sum_i d_i \geq \tau_{\text{safe}} \Rightarrow$ auto-allocate per the chosen objective.
   - $s / \sum_i d_i < \tau_{\text{safe}} \Rightarrow$ classify as `AtRisk_Severe` and route to human review.
   - $\tau_{\text{safe}}$ is **config-declared, not hardcoded.** Default value $0.90$ for the trial deliverable; per-retailer or global override permitted.

**Alternatives.**

- Closed-form weighted heuristic $x_i = (\rho_i \cdot d_i) \cdot s / \sum$. Rejected as Gemini caught: violates $x_i \leq d_i$ under skewed $\rho$.
- Max-min fair as default. Rejected: large retailers take disproportionate cuts under stress; commercially fragile.
- Hardcoded $\tau_{\text{safe}} = 0.90$. **Modified from Gemini's recommendation:** hardcoding was justified for "demonstrate the pattern to reviewers"; the math doesn't support a fixed value. Lock the *pattern* as a service-level-agreement framework, leave the *value* configurable. Default $0.90$ is fine for the trial deliverable.

**Why.** Pro-rata is the safe commercial default; water-filling rescues the weighted generalization from the upper-bound bug; fill-rate thresholding is the canonical OR pattern for the auto-vs-review boundary. Captured rigorously rather than punted.

**Captured in:** [`primitives/CPG/allocation.md`](primitives/CPG/allocation.md), [`docs/architecture/formalism.md`](docs/architecture/formalism.md) §5.

---

## D-011 — Confidence calibration: Fellegi-Sunter for exact strata, Jaro-Winkler² for fuzzy, Cascaded Classification for production

**Date:** 2026-05-09 (initial), updated 2026-05-09 with iterations 8 & 9
**Status:** **locked** — all sub-gaps from initial provisional lock have been resolved
**Source:** Gemini iterations 5, 8, 9 (`raw-truth.md`).

**Decision (locked parts).**

1. **Fuzzy-match scoring (stratum E_4):** Use **Jaro-Winkler similarity** (canonical for short record-linkage; weights prefix matches heavily — appropriate for SKU strings where brand prefixes carry signal). Confidence is $w = x^2$ (or $x^3$) where $x$ is the Jaro-Winkler similarity, suppressing mid-tier vibes-y matches and creating contrast between true matches and noise.

2. **Production calibration path (≥ ~200 labels):** Logistic regression (Platt scaling) over multi-feature input — Jaro-Winkler similarity, token-overlap (TF-IDF weighted), vertex degree in the bipartite graph — trained on operator review resolutions. Beta calibration as alternative for bounded scores.

3. **Information-theoretic alias scoring (TF-IDF):** Per Gemini's option 1, treat the ERP master as a corpus and weight matched-token IDF. Originally deferred; **partially implemented** as stratum E3b per D-013 (token-overlap gated at `tfidf_min_score=0.5`, `tfidf_min_matched_tokens=2`).

**Future upgrade path beyond LR-as-calibrator: isotonic regression at $N \gtrsim 1000$.**

In the production v1 cascaded-classification framing (per Gemini iteration 9), a single LR is doing both feature combination and calibration. That single-stage approach is reasonable for moderate label sets but can leave systematic miscalibration in the tails when the true score-to-probability mapping isn't a clean logistic. **Isotonic regression** as a *separate* calibration layer (downstream of the LR combiner) is non-parametric and monotonic — it makes no shape assumption beyond order-preservation, which fits the underlying intuition (higher score → higher probability) without committing to a functional form.

**Trigger to migrate:** when the labeled review-resolution log reaches $N \gtrsim 1000$ entries with reasonable coverage across the score range, separate the combiner from the calibrator and swap LR-as-calibrator for isotonic. At that scale the non-parametric flexibility starts paying off without overfitting. Below that threshold, isotonic tends to overfit the empirical CDF; the LR's parametric form is the right regularizer.

**Migration mechanics:** the upgrade is local to the calibration layer — same combiner inputs, same output semantics (calibrated probability), drop-in replacement of the calibration head. No changes to the cascade, the Fellegi-Sunter scores, the bipartite graph, or `MappingResult` shape.

**Beta calibration** remains a parallel alternative — useful specifically for the *single-feature* path (e.g., calibrating $\mathrm{JW}^2$ alone, where Kull-Filho-Flach 2017 shows beta outperforms Platt on bounded scores). Worth A/B-comparing against isotonic when the migration happens; not required at trial scope because the FS posteriors are already calibrated.

**Decision update — gap (b) resolved by Gemini iteration 9 (MATH-SOT-IT3 follow-up B response):**

b. ✅ **Cascade-band consistency: drop strict bands; cascade is a *blocking strategy*, scoring is independent.** The cascade $E_1 \succ E_2 \succ E_3 \succ E_4$ governs **discovery order** (which stratum fires first, with lower strata preempted) but does **not** constrain the resulting confidence score. Each stratum produces a probability score on its own merit; an unusually high-quality $E_4$ match can legitimately score above an ambiguous $E_3$ match.

The standard published framing is **Cascaded Classification**: the supervised production calibrator is a single logistic regression over `[score] + [stratum-indicator I_k]`, learning a structural baseline penalty per stratum ($\beta_4 < \beta_3 < \beta_2 < \beta_1$) so the *expected* ordering is preserved while the data-driven overlap remains:

$$P(\text{Match} = 1 \mid \text{Score}, \text{Stratum}) = \sigma\!\left( w_0 + w_1 \cdot \text{Score} + \sum_k \beta_k \cdot I_k \right)$$

UX consequence: the review-queue surface separates **Lineage** (categorical: `[Tag: Exact GTIN]` / `[Tag: Fuzzy Alias]`) from **Confidence** (raw probability). The auto-allocate tripwire becomes a *single global threshold* on confidence (no per-stratum thresholds) — at production scope where the LR has produced calibrated probabilities.

**Pushback / nuance worth noting:** Gemini's "globally unified tripwire" assumes calibrated probabilities, which are a *production-scope* artifact (post-supervised LR). At **trial scope** we have only crudely calibrated scores (Jaro-Winkler² for fuzzy; band-derived for exact, pending follow-up A). A single global threshold at trial scope is more conservative than at production scope; treat the threshold as `provisional` until calibration data accumulates.

**Decision update — gap (a) resolved by Gemini iteration 8 (Fellegi-Sunter framework):**

a. ✅ **Per-stratum exact-match scores via Fellegi-Sunter (1969).** Replace stratum bands with **per-match dynamic posteriors** driven by the empirical collision rate $K_x$ (number of distinct ERP SKUs sharing the matched key $x$) and three unsupervised priors:

| Stratum | Formula | Hyperparameter |
|---|---|---|
| $E_1$ (current_gtins) | $w_1(x) = (1 - \epsilon) / K_x$ | $\epsilon$ = global data-corruption prior |
| $E_2$ (legacy_gtins)  | $w_2(x) = (1 - \gamma)(1 - \epsilon) / K_x$ | $\gamma$ = legacy-obsolescence rate |
| $E_3$ (aliases)       | $w_3(x) = (1 - \epsilon) / K_x^{\alpha}$ | $\alpha > 1$ = alias-collision dampening exponent |
| $E_4$ (fuzzy)         | $w_4(x) = \mathrm{JW}(x)^2$ | (Jaro-Winkler² per iteration 5) |

**Default initial values (per Gemini worked example, treat as starting points pending labeled-data tuning):**

- $\epsilon = 0.02$ (2% baseline retailer error rate)
- $\gamma = 0.10$ (10% legacy obsolescence risk)
- $\alpha = 1.5$ (alias collision dampening)

**Implementation hint (locked):** inside the retailer adapter's `normalize_forecast()` (or equivalent), pre-compute the frequency dictionary $K_x$ for every key in the ERP master at startup. On a match at any stratum, execute the corresponding formula. No labeled data required.

**Why this is materially better than static bands:**

- **Self-correcting on overloaded keys.** A colliding `current_gtin` ($K_x = 2$) yields $w_1 = 0.49$, plunging out of any "auto-map" zone — exactly the operator-review behavior we want. Static bands $[0.95, 1.00]$ would have silently auto-allocated to a random variant.
- **Self-correcting on generic aliases.** "Spicy Chorizo" with $K_x = 3$ yields $w_3 \approx 0.18$ under the dampening exponent, demanding review without manual band-tuning.
- **Naturally unbanded** — consistent with iteration 9's "drop strict bands" lock. Each match scores on its own merit.

**Pushback / nuance worth recording:**

- The hyperparameters $\epsilon, \gamma, \alpha$ are themselves *unsupervised priors*. We've reduced the vibes surface from 8 numbers (4 stratum bands × 2 endpoints) to 3 hyperparameters — a real principled improvement, but not vibes-free. Once $\sim 200$ labels accumulate, $\epsilon, \gamma, \alpha$ themselves become learnable from the supervised review-resolution stream.
- The dampening exponent $\alpha = 1.5$ for aliases is justified intuitively (aliases are inherently fuzzier identifiers than GTINs) but not derived. Tunable as labels arrive.
- Gemini's formula simplifies the full Fellegi-Sunter likelihood ratio by assuming $m \approx 1$ (true matches almost never disagree on the matched key) and uniform prior over candidates within $K_x$. Both are reasonable for exact-match strata at trial scope; production refinement could relax these.

### Implication for the beta-vs-Platt-vs-isotonic question

A side-effect of locking the Fellegi-Sunter framework: **at trial scope, the per-stratum scores are themselves principled posterior probabilities** ($w \in [0, 1]$, derived from collision rates and priors). They are **not raw similarity scores requiring post-hoc calibration** — they're already calibrated under the model's assumptions.

This sharpens the calibration table:

| Stage | Trial scope (no labels) | Production v1 (~200 labels) | Production v2 (~1000+ labels) |
|---|---|---|---|
| Per-match score | Fellegi-Sunter for $E_1, E_2, E_3$; JW² for $E_4$ | Same; tune $\epsilon, \gamma, \alpha$ from labeled data | Same |
| Combine across features | n/a (use the score directly) | Cascaded Classification LR over `[score, stratum-indicator, JW, TF-IDF, vertex_degree]` | Same combiner (or upgrade to GBM) |
| Calibrate | Trust the FS posterior directly | LR's sigmoid serves as the calibrator (single-stage, per Gemini iteration 9); **beta calibration optional refinement** if LR shows tail miscalibration | Replace LR-as-calibrator with **isotonic regression** |

**Beta calibration is no longer needed at trial scope** (FS gives a principled probability directly) and is an **optional refinement** at production scope (parallel to LR-as-calibrator, useful specifically when the LR sigmoid shows tail miscalibration on the bounded JW² input).

**Decision update — gap (b) resolved by Gemini iteration 9 (covered above).**

**Alternatives considered.**

- TF-IDF for fuzzy scoring. Originally deferred; partially shipped as E3b per D-013.
- Normalized Levenshtein. Rejected: linear penalty mis-models SKU-string editing reality.
- Embedding cosine. Out of scope at trial budget.

**Why.** Locks the parts that are unambiguously correct (Jaro-Winkler shape, Platt-scaling production path). Sub-gaps around band derivation and cascade consistency were resolved via iterations 8 and 9; status is now **locked**.

**Captured in:** [`primitives/CPG/entity-resolution.md`](primitives/CPG/entity-resolution.md), [`docs/architecture/formalism.md`](docs/architecture/formalism.md) §3.

---

## D-012 — Drift signal: lagged-actuals plausibility check (not classical residual drift)

**Date:** 2026-05-10
**Status:** locked
**Source:** Plan extension #3; fixture limitation (no W19 forecast in trial data).

**Decision.** Trial-scope drift detection is implemented as a **lagged-actuals-vs-forecast plausibility check**, not classical residual drift. For each (retailer, sku) with a Resolved mapping:

$$
\rho = \frac{\text{forecast\_eaches}_{t+1}}{\max(\text{actuals\_eaches}_t,\ 1)}
$$

with thresholds $[\tau_{\text{low}},\, \tau_{\text{high}}] = [0.5,\, 1.5]$ (configurable). Outside that range, `direction` is `high` or `low`; inside, `ok`.

**Promo segmentation.** Forecast rows with `promo_flag=True` (Tesco only — Sainsbury's has no promo column) are excluded from threshold-based flagging because promo creates expected uplift. The asymmetric retailer support is recorded in the signal as `promo_flag` and `promo_segmented` fields.

**Skipped unmapped.** Forecast rows whose mapping is `Blocked` or `NeedsVerification` are not turned into signals — they're counted under `summary["skipped_unmapped"]`. This preserves signal-stream cleanliness and surfaces the volume of un-comparable lines separately.

**Alternatives rejected.**

- **Classical residual drift** $r_t = a_t - f_t$: requires a forecast and actuals from the *same* period. Trial fixture has only forward forecasts (W20) and lagged actuals (W19); the same-period pair doesn't exist. Out of scope until historical forecasts are archived.
- **Markov-style time-series detection**: reserved per **D-006** for production scope where multi-week residual histories accumulate. Explicitly deferred.
- **Drift-driven auto-allocation pause**: a "stop drafting if drift is high" gate is a downstream commercial decision; the trial-scope tool produces signals only.

**Why.** The fixture forces the framing. Naming what we *can* compute (recency-baseline) honestly is more rigorous than overclaiming classical drift. The promo-segmentation gate handles the fixture's most obvious noise source. Markov is reserved, not discarded — D-006 already established that intent.

**Captured in:** [`docs/architecture/formalism.md`](docs/architecture/formalism.md) §10, [`src/verdano/drift/`](src/verdano/drift/) (module), [`src/verdano/pipeline/drift.py`](src/verdano/pipeline/drift.py) (entry-point), [`src/verdano/mcp_server/server.py`](src/verdano/mcp_server/server.py) (`compare_actuals_vs_forecast_tool`), [`tests/drift/test_baseline.py`](tests/drift/test_baseline.py) (7 tests).

---

## D-013 — Canonicalization upgrades: size-unit normalizer + TF-IDF stratum `tfidf_overlap` (formerly E3b)

**Date:** 2026-05-10
**Status:** locked
**Source:** User request to add the two "free precision" wins from the canonicalization gap analysis (post-trial polish, low-risk additive code).

**Decision.** Two unsupervised canonicalization improvements layer on top of the existing cascade without changing its discovery semantics:

### 1. Size-unit normalizer in `_norm()`

Pure regex preprocessor that converts `kg → g` and `l → ml` symmetrically on both the master alias index and retailer-side lookup strings:

$$
\text{normalize}(s) \;=\; \text{size-rescale}\bigl(\text{lower}(s)\bigr)
$$

where the size rescale is `(\d+(?:\.\d+)?)\s*(kg|l)\b` → `value × 1000` with the unit swapped. Idempotent. Falsifies on `100ml`, `1lb`, `kgallon` (regex word-boundary guards). Implementation in `src/verdano/mapping/normalize.py`.

This closes the size half of the deliberate fixture gotcha **"Tom Basil Soup 0.5kg" ↔ "Tomato Soup 500g"** at the lexical layer (the alias-curation half is already handled by the ERP master).

### 2. TF-IDF stratum `tfidf_overlap` (formerly E3b)

A new stratum inserted **between E3 (alias exact) and E4 (Jaro-Winkler² fuzzy)** in the cascade. Per Gemini iteration 5 option 1:

$$
\text{score}(s, P) \;=\; \frac{\sum_{t \in \text{tokens}(s) \cap \text{vocab}(P)} \text{IDF}(t)}{\sum_{t \in \text{tokens}(s)} \text{IDF}(t)}
$$

Range $[0, 1]$. Interpret as the fraction of the retailer string's information content supported by ERP product $P$'s vocabulary (canonical name + aliases).

**Cascade firing rule:** `tfidf_overlap` fires when `alias_exact` misses and the top TF-IDF score $\geq \tau_{\text{tfidf}}$ (default 0.5, configurable). Below the threshold, fall through to `fuzzy_jw`. **Confidence emitted** = `top_score × (1 − ε) / K_x^α`, applying the same Fellegi-Sunter ambiguity penalty as `alias_exact` (so tied candidates collapse to NeedsVerification).

Smoothed IDF: `log(N / (1 + df)) + 1` (sklearn-style; never zero, never negative). Implementation in `src/verdano/mapping/tfidf.py`.

**Cascade after D-013:**

| Rung | Source | Score |
|---|---|---|
| `gtin_current` (formerly $E_1$) | exact `current_gtins` | $(1-\epsilon)/K_x$ |
| `gtin_legacy` (formerly $E_2$) | exact `legacy_gtins` | $(1-\gamma)(1-\epsilon)/K_x$ |
| `alias_exact` (formerly $E_3$) | exact alias / canonical name | $(1-\epsilon)/K_x^{\alpha}$ |
| **`tfidf_overlap`** (formerly $E_{3b}$) | **TF-IDF token overlap** ≥ τ_tfidf | **$\text{tfidf}(s,P) \cdot (1-\epsilon)/K_x^{\alpha}$** |
| `fuzzy_jw` (formerly $E_4$) | Jaro-Winkler² on canonical name | $\mathrm{JW}(s)^2$ |

**Empirical effect on the fixture.** The deliberate "Falafel Bowl" Sainsbury row (no GTIN, ambiguous between `Falafel Bowl 350g` and `Falafel Bowl Large`) now resolves via **`tfidf_overlap` with K_x = 2** instead of `fuzzy_jw` with K_x = 1. Both routes produce NeedsVerification, but `tfidf_overlap`'s K_x reflects the actual ambiguity in the data — operators see "two candidates tied" rather than "one fuzzy guess."

**Alternatives rejected.**

- **TF-IDF as a discovery-only mechanism** (don't gate by threshold). Rejected: every retailer string would resolve via E3b for *some* ERP product, which collapses E4 into dead code and hides genuine no-match cases.
- **Replace E3 with TF-IDF entirely.** Rejected: when the alias exact-match exists, the FS posterior is mathematically tighter than the IDF-weighted overlap. E3 stays as the high-confidence rung.
- **TF-IDF + size-unit at the same time** (one large change). Rejected: the size normalizer is independently useful at every cascade stratum (alias index, fuzzy search, TF-IDF tokenization); it gets its own pass.
- **Brand-prefix stripping, stop-word removal, plural↔singular.** Deferred. The trial fixture doesn't force these and they introduce ambiguity at small data scale.

**Pushback / nuance worth recording.**

- TF-IDF asymmetry: the score is normalized by the *retailer*'s IDF mass, not the product's. A short retailer string with a single rare token can score highly against any product containing that token. The threshold gate (default 0.5) and the FS ambiguity penalty mitigate but don't eliminate this. Calibration data would let us learn a better threshold.
- Tokenization is whitespace-only. Punctuation handling is implicit (whitespace-collapse strips leading/trailing punctuation but doesn't split `a&b` into `a` and `b`). Trial fixtures don't trigger this; if production data does, the normalizer is the place to extend.
- The IDF table is built once at `MasterIndex` construction. If the ERP master grows substantially (drops a token's df), recompute by reconstructing the index — there's no incremental update.

**Captured in:** [`src/verdano/mapping/normalize.py`](src/verdano/mapping/normalize.py), [`src/verdano/mapping/tfidf.py`](src/verdano/mapping/tfidf.py), [`src/verdano/mapping/resolver.py`](src/verdano/mapping/resolver.py) (cascade integration), [`src/verdano/canonical/models.py`](src/verdano/canonical/models.py) (Stratum registry includes `tfidf_overlap`), [`tests/mapping/test_normalize.py`](tests/mapping/test_normalize.py) (23 tests), [`tests/mapping/test_tfidf.py`](tests/mapping/test_tfidf.py) (7 tests), [`docs/architecture/formalism.md`](docs/architecture/formalism.md) §3.5 (cascade table).

---

## D-014 — Cascade-floor and dedup fixes (post-D-013 empirical probe)

**Date:** 2026-05-10
**Status:** locked
**Source:** Direct probe of the live ERP master + adversarial stress-testing of the cascade with garbage strings and edge-case retailer inputs. Three real misalignments surfaced; all three fixed below.

**Decision (three independent fixes, applied together).**

### 1. Same-SKU dedup in `MasterIndex` (bug fix, not design change)

The pre-fix `MasterIndex` appended SKUs to a `defaultdict(list)` for each key. When D-013's size normalizer collapsed a product's *canonical name* and one of its *aliases* to the same canonical string (e.g., `"Carrot Ginger Soup 500g"` and `"Carrot Ginger Soup 0.5kg"` both → `"carrot ginger soup 500g"`), the same SKU appeared twice in the index value list. Lookup-time `K_x = len(candidates) = 2` falsely triggered the Fellegi-Sunter ambiguity penalty: `(1−0.02)/2^1.5 = 0.346` → NeedsVerification on a perfectly-clean exact match.

**Fix.** Build per-key SKU **sets** during index construction; serialize to sorted lists at the end. Same-SKU duplication can never inflate K_x. Applied uniformly to `current_gtin`, `legacy_gtin`, and `alias` indexes (the GTIN case is defensive — protects against a product listing its own GTIN twice in the master, which the trial fixture doesn't exhibit but a production system might).

### 2. `fuzzy_jw` (formerly E4) minimum-confidence floor (`fuzzy_jw_min_score`, née `e4_min_score`, default 0.30)

Empirical stress test surfaced the failure mode:

```
'Vegan Patty'      → JW² = 0.280  →  NeedsVerification candidate VG-DAAL-400 (Lentil Dal)
'qwerty asdf'      → JW² = 0.299  →  NeedsVerification candidate VG-CARR-500 (Carrot Ginger)
'Ice Cream Cone'   → JW² = 0.336  →  NeedsVerification candidate VG-THAI-400 (Thai Green)
```

Every garbage retailer string returned *some* candidate. The operator UI surfaces these as "Bicycle Tyre might be Chickpea Curry 400g — please verify." That's actively misleading: no candidate is the truthful response. Better to return **Unmapped** below a confidence floor.

**Fix.** Add `fuzzy_jw_min_score` (originally `e4_min_score`, renamed per D-018; default `0.30` — empirically catches the worst garbage strings without cutting borderline-legitimate fuzzy matches). Below the floor, the cascade returns `Unmapped` instead of `NeedsVerification` with a wrong candidate. The legacy env var `VERDANO_E4_MIN_SCORE` is still accepted via a backward-compat alias.

**Pushback worth recording.** The floor value is itself an unsupervised choice. At trial scope `0.30` is calibrated against the observed JW² range of obvious-garbage inputs (`0.20–0.34`). Production-scope tuning would benefit from labeled review-queue resolutions: count garbage flagged as Unmapped vs. legitimate matches accidentally suppressed, learn the boundary.

### 3. `tfidf_overlap` (formerly E3b) minimum-matched-tokens guard (`tfidf_min_matched_tokens`, default 2)

The TF-IDF score is `Σ_match IDF(t) / Σ_retailer IDF(t)` — normalized by the *retailer's* IDF mass. For a retailer string with a single token that happens to appear in exactly one ERP product (a high-IDF rare token), the ratio is **1.0** — full coverage of retailer information. K_x = 1 (single product matched). Confidence: `1.0 × 0.98 / 1^1.5 = 0.98` → **auto-Resolved**.

Empirical demonstration on the live master:

```
'VD'               top_score=1.000  candidates=['VG-DAAL-400']
                                    → previously E3b @ 0.98 (Resolved!)
```

The retailer sending the literal string `"VD"` would auto-allocate against Lentil Dal because that product has alias `"VD Lentil Dal 400g"`. Operationally indefensible — one shared rare token isn't enough information for an auto-allocation decision.

**Fix.** Add `tfidf_min_matched_tokens` (default `2`). E3b only fires when at least 2 retailer tokens overlap with the candidate's vocabulary. Single-token retailer strings can never trigger E3b auto-allocation.

**Pushback worth recording.** This is conservative. A rare 1-token match might *occasionally* be the right answer (e.g., a retailer string that's literally just a unique brand-coded SKU like `"VD-001"`). The guard sacrifices that edge case for the much-more-common false positive. Operator-configurable — set `tfidf_min_matched_tokens=1` to disable.

**Alternatives rejected.**

- **No guard, raise `tfidf_min_score` instead.** Rejected: the score is 1.0 on the failure mode (single full-coverage token); raising the score threshold doesn't help.
- **Penalize single-token strings via a different scoring function.** Rejected: complexity-without-clarity. A discrete count guard is simpler and matches operator intuition.
- **Drop E3b entirely, use E4 (Jaro-Winkler²) for everything.** Rejected: E3b's IDF-weighting still captures the multi-token-overlap pattern that JW² misses (e.g., "Falafel Bowl" hitting K_x=2 ambiguity cleanly).

**Joint verification.**

| Input | Pre-D-014 | Post-D-014 |
|---|---|---|
| `"Carrot Ginger Soup 500g"` | E3 K=2 w=0.346 NeedsVerification ❌ | E3 K=1 w=0.980 Resolved ✓ |
| `"VD"` | E3b K=1 w=0.980 Resolved ❌ | Unmapped ✓ |
| `"Vegan Patty"` | E4 w=0.280 NeedsVerification ❌ (misleading candidate) | Unmapped ✓ |
| `"Falafel Bowl"` | E3b K=2 w=0.346 NeedsVerification ✓ | E3b K=2 w=0.346 NeedsVerification ✓ (unchanged) |
| `"Falafel only"` (1 retailer token, 1 match) | E3b K=2 w=auto-Resolved ❌ | E4 fall-through w=0.78 NeedsVerification ✓ |

**Captured in:** [`src/verdano/mapping/resolver.py`](src/verdano/mapping/resolver.py) (`MasterIndex` set-based dedup; `Resolver` floor + min-tokens parameters; `_count_matched_tokens` helper), [`tests/mapping/test_resolver_floors.py`](tests/mapping/test_resolver_floors.py) (7 tests covering all three fixes + their configurability).

---

## D-015: `RetailerCode` extensibility — registry pattern implemented

**Date:** 2026-05-10 | **Updated:** 2026-05-10

**Context:** D-001 claims "no new Python" for onboarding a new retailer. This is true at the adapter spec layer — a new `RetailerSpec` instance is all the application code needs. The type system boundary previously used `RetailerCode = Literal["tesco", "sainsburys"]`, requiring a code change to extend.

**Resolution:** `RetailerCode` is now a plain `str` alias with a runtime registry. `register_retailer(code, spec)` in `adapters/spec.py` is the single entry point for onboarding — it registers both the spec and the retailer code. MCP tool boundaries call `validate_retailer_code()` for runtime validation. Trade-off: FastMCP tool schemas now accept any string instead of showing an enum (type safety at small scale vs extensibility at large scale).

**Captured in:** [`src/verdano/canonical/models.py`](src/verdano/canonical/models.py) (registry + validation), [`src/verdano/adapters/spec.py`](src/verdano/adapters/spec.py) (`register_retailer`), [`tests/test_negative.py`](tests/test_negative.py) (4 registry tests).

---

## D-016: Config externalization — thresholds hoisted into `Settings`

**Date:** 2026-05-10

**Context:** Twelve numeric thresholds were scattered as constructor defaults across `classify.py`, `resolver.py`, `priors.py`, `baseline.py`, and `depot.py`. Changing any value required a code deploy. Operators and reviewers had no single surface to inspect or override tuning parameters.

**Resolution:** All thresholds now live in `src/verdano/config.py::Settings`, inheriting `VERDANO_` env-prefix via pydantic-settings. Non-secret values can be set in `.env` or as env vars; secrets (`llm_api_key`) use `SecretStr`. The MCP server loads `Settings` once at startup and passes values through to the pipeline, resolver, classifier, and drift comparator. Existing default values are preserved — the change is purely structural, no behavioral regression.

**Additionally:** `FulfillmentClass`, `MappingState`, `DriftClass`, and `Stratum` were converted from `Literal` types to `str` aliases with runtime registries (same pattern as `RetailerCode` in D-015). This enables adding new classification tiers, mapping states, or cascade strata without editing source files. Strata now use semantic names per D-018.

**Captured in:** [`src/verdano/config.py`](src/verdano/config.py), [`src/verdano/canonical/models.py`](src/verdano/canonical/models.py) (registries), [`src/verdano/mcp_server/server.py`](src/verdano/mcp_server/server.py) (wiring), [`.env.example`](.env.example).

---

## D-017: LLM integration layer — provider-agnostic, optional

**Date:** 2026-05-10

**Context:** Entity resolution strata `gtin_current`–`fuzzy_jw` (formerly E1–E4) are purely algorithmic. For ambiguous or novel product names that none of the strata resolve confidently, a language model can provide a contextual fallback. Similarly, depot-string resolution sometimes fails on novel location labels.

**Resolution:** New `src/verdano/llm/` package with:
- `LLMClient` protocol + `OpenAIClient` implementation using configurable `base_url` (OpenAI, Azure, Ollama, vLLM all speak the same API).
- `llm_augmented` (formerly E5) stratum handler (`make_llm_stratum`) that sends top-N fuzzy candidates to the LLM for disambiguation. Plugs into the cascade via the handler chain — no if/elif surgery.
- LLM depot fallback in `depot.py` — if fuzzy match fails and an `LLMClient` is available, asks the LLM to interpret the location label.
- All LLM features are **optional**: if `VERDANO_LLM_API_KEY` is empty, `create_llm_client` returns `None` and the cascade works exactly as before.

The normalizer was refactored from a monolithic function into a composable `NormalizationPipeline` of `NormalizerStep` callables, enabling extension (brand stripping, stop words) without editing source. The resolver was refactored from hardcoded if/elif blocks to an ordered `StratumHandler` chain.

**Trade-off:** LLM calls add latency and cost. The `llm_augmented` stratum only fires after the algorithmic strata fail, and only when configured. Operators can disable it by omitting the API key.

**Captured in:** [`src/verdano/llm/`](src/verdano/llm/) (client, entity_resolution), [`src/verdano/mapping/resolver.py`](src/verdano/mapping/resolver.py) (handler chain), [`src/verdano/mapping/normalize.py`](src/verdano/mapping/normalize.py) (pipeline), [`src/verdano/mapping/depot.py`](src/verdano/mapping/depot.py) (LLM fallback).

---

## D-018: Semantic stratum naming — E-notation replaced with self-documenting identifiers

**Date:** 2026-05-10

**Context:** The cascade strata were labeled `E1`, `E2`, `E3`, `E3b`, `E4`, `E5` — opaque identifiers inherited from the mathematical formalism (`$E_1 \succ E_2 \succ \ldots$`). These names required a lookup table to interpret, made code review harder, and created a maintenance hazard as the cascade grew (e.g. the awkward `E3b` insertion).

**Resolution:** All stratum identifiers renamed to semantic, self-documenting names:

| Legacy | Semantic | Handler function |
|--------|----------|-----------------|
| E1 | `gtin_current` | `_handle_gtin_current` |
| E2 | `gtin_legacy` | `_handle_gtin_legacy` |
| E3 | `alias_exact` | `_handle_alias_exact` |
| E3b | `tfidf_overlap` | `_handle_tfidf_overlap` |
| E4 | `fuzzy_jw` | `_handle_fuzzy_jw` |
| E5 | `llm_augmented` | `_handle_llm_augmented` |

The rename spans source files, tests, and active documentation. The mathematical formalism (`formalism.md`) retains `$E_1$`–`$E_4$` notation in LaTeX expressions with a cross-reference note; historical transcripts (`raw-truth.md`, `prompts-for-gemini.md`) are left untouched.

**Trade-off:** New strata can now be inserted anywhere in the chain with descriptive names (e.g. `brand_prefix`, `embedding_similarity`) without the E-numbering fragility. Anyone reading older decisions or the formalism can cross-reference via the mapping table above.

**Captured in:** [`src/verdano/mapping/resolver.py`](src/verdano/mapping/resolver.py) (handler renames + DEFAULT_HANDLERS), [`src/verdano/canonical/models.py`](src/verdano/canonical/models.py) (registry seeds), [`src/verdano/llm/entity_resolution.py`](src/verdano/llm/entity_resolution.py), [`src/verdano/mcp_server/server.py`](src/verdano/mcp_server/server.py), 8 test files.

---

## D-019: LLM post-cascade re-ranker — validator mode for false-positive detection

**Date:** 2026-05-10

**Context:** The `llm_augmented` stratum (D-017) sits at position 6 of 6 in the cascade, firing only when *all* deterministic strata fail. For well-aliased datasets this means the LLM never activates — the cascade short-circuits at `alias_exact` or earlier. The more dangerous failure mode is *false positives from earlier strata*: a stale alias or weak fuzzy hit resolving to the wrong product at high confidence, with no second opinion.

**Resolution:** Add a **re-ranking pass** that runs *after* the cascade resolves each line. The re-ranker selectively sends low-confidence or stratum-gated matches to the LLM for validation:

- **`rerank_threshold`** (default 0.92): mappings below this confidence are re-ranked.
- **`rerank_strata`** (default `{tfidf_overlap, fuzzy_jw}`): mappings from these strata are *always* re-ranked regardless of confidence.
- **`rerank_min_llm_confidence`** (default 0.70): the LLM must exceed this confidence for its disagreement to take effect.

If the LLM agrees, the mapping is unchanged. If the LLM disagrees with sufficient confidence, the mapping's state is downgraded from `Resolved` to `NeedsVerification` and evidence is replaced with `stratum="llm_rerank"` so operators see why it was flagged. On any LLM failure, the original mapping is preserved (graceful degradation).

**Trade-off:** The existing `llm_augmented` fallback stratum is *preserved* for total cascade misses. The re-ranker is orthogonal — it validates *successful* cascade hits. Without an LLM key the re-ranker is a complete no-op. High-confidence GTIN matches (0.98+) are never sent to the LLM, keeping API cost proportional to ambiguity. All three parameters are configurable via `Settings` / environment variables.

**Captured in:** [`src/verdano/llm/reranker.py`](src/verdano/llm/reranker.py) (core logic), [`src/verdano/pipeline/analyze.py`](src/verdano/pipeline/analyze.py) (integration), [`src/verdano/config.py`](src/verdano/config.py) (settings), [`tests/test_reranker.py`](tests/test_reranker.py) (16 tests).

---

## D-020: Drift module extensibility refactor — strategy pattern + residual mode

**Date:** 2026-05-10

**Context:** The drift module was the only subsystem not built with the same extensibility patterns as the rest of the codebase. The cascade resolver has `StratumHandler` chains (D-018); the adapters have `RetailerSpec` configs (D-001); the classifier has runtime registries (D-016). But drift had a monolithic `BaselineCompare` class with one hardcoded algorithm, a closed `Literal` type for `DriftDirection`, a frozen `DriftSignal` model that couldn't carry residual fields, and hardcoded CSV paths tied to the trial fixture's filenames.

**Resolution:** Refactor drift to follow the same patterns as D-016 (runtime registries) and D-018 (handler chains):

1. **`DriftDirection` → runtime registry:** Replace `Literal["high", "low", "ok"]` with `str` + `register_drift_direction()` + `_DRIFT_DIRECTION_REGISTRY`. Residual mode registers `over_forecast`, `under_forecast`, `accurate` without editing `types.py`.
2. **`DriftSignal` extensibility:** Add optional `mode`, `residual`, `pct_error` fields alongside the existing `ratio` field. Both modes populate the common fields (`forecast_eaches`, `actuals_eaches`, `direction`, `reason`); mode-specific fields are `None` when inapplicable. Relaxed `extra="forbid"` to plain `frozen=True`.
3. **Strategy pattern:** Introduce `DriftStrategy = Callable[[DriftContext], DriftReport]`, a `DriftContext` dataclass holding shared inputs, and a `DriftAnalyzer` dispatcher. The existing ratio logic is extracted into `plausibility_strategy`; a new `residual_strategy` computes `r = actuals − forecast` with configurable `residual_threshold`. `BaselineCompare` is preserved as a thin backward-compatible wrapper.
4. **Pipeline + MCP:** `analyze_drift(mode=...)` replaces the internal call path; `analyze_forecast_plausibility` is preserved as a backward-compatible alias. The `compare_actuals_vs_forecast_tool` gains an optional `mode` parameter (default `"plausibility"`). Residual mode validates `iso_week_forecast == iso_week_actuals` and returns a clear error if weeks differ.
5. **Generic CSV resolver:** `_data_csv_for(retailer, kind, iso_week, root)` tries `{retailer}_{kind}_week{NN}.csv` first, then falls back to legacy filenames, so the system works with new data files without code changes.
6. **Config:** Added `drift_residual_threshold` (default 0.10) to `Settings`.

**Trade-off:** The existing `plausibility` mode behavior is preserved exactly — all 7 original drift tests pass unchanged. The refactor adds 19 new tests (26 total drift tests). The MCP tool signature is backward-compatible; callers that don't pass `mode` get the current behavior. Future drift modes (Markov, learned DOW kernel) slot in as additional strategy functions registered in `DEFAULT_STRATEGIES`.

**Captured in:** [`src/verdano/drift/types.py`](src/verdano/drift/types.py) (registry), [`src/verdano/drift/baseline.py`](src/verdano/drift/baseline.py) (protocol + plausibility), [`src/verdano/drift/strategies.py`](src/verdano/drift/strategies.py) (residual), [`src/verdano/pipeline/drift.py`](src/verdano/pipeline/drift.py) (entry-point), [`src/verdano/mcp_server/server.py`](src/verdano/mcp_server/server.py) (tool + CSV resolver), [`src/verdano/config.py`](src/verdano/config.py) (threshold), [`tests/drift/`](tests/drift/) (26 tests).

---
