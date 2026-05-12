# Mathematical formalism — CPG reconciliation layer

This document is the **co-created mathematical model** of the system. It draws on the Gemini conversation in [`raw-truth.md`](../process/raw-truth.md) but is not subordinate to it — Gemini provided sketches; this document is where we make the math precise, push back where the sketches mislead, and surface the gaps.

The formalism is **iterative**. Sections 3–7 are first-pass and will sharpen. Section 8 makes the divergences from the Gemini source explicit. Section 9 names the open mathematical questions deferred for later iteration.

---

## 0. Scope

### 0.1 What we model

The CPG Reconciler trial is an **integration and reconciliation layer** between retailer-published facts and an external ERP. We model:

- **Entity resolution** between retailer-side identifiers and ERP-side identifiers (§3).
- **Demand alignment** between incompatible bases for the same demand quantity (§4).
- **Allocation** of ERP supply against resolved retailer demand under physical constraints (§5).
- **Workflow** — the lifecycle FSM for order drafts and the DAG of computations that drive it (§6).
- **Idempotency** as a structural property of the side-effecting boundary (§7).

### 0.2 What we deliberately do *not* model

Per **D-005** in [`DECISIONS.md`](../../DECISIONS.md):

- **ERP-internal mathematics** — General Ledger null-space constraints ($\mathbf{1}^T W = \mathbf{0}^T$), referential-integrity inclusion dependencies, RBAC permission composition, Segregation-of-Duties negative constraints. These are the ERP's job and they're behind the API boundary. The mathematical sketches in [`raw-truth.md`](../process/raw-truth.md) iteration 2 are preserved as grounding context but are not load-bearing for the build.
- **ERP-internal process cycles** — P2P, R2R. We touch the front edge of O2C only.
- **ERP-internal modules** — Financials / HCM / Supply Chain as user-facing pillars.

### 0.3 What we model *with* mathematics rather than just types

Not every part of the system needs a mathematical model. We use math where it actually constrains the implementation: where the math forces a question (what's the disaggregation kernel?), names a gap (confidence calibration), or makes an invariant precise (idempotency, total-preservation under aggregation).

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| $\mathcal{P}_{\text{CPG}}$, $\mathcal{P}_{\text{ERP}}$ | The CPG-side and ERP-side primitive spaces (§2). |
| $V_R$, $V_E$ | Retailer-published identifier set; ERP canonical identifier set. |
| $G = (V_R \cup V_E, E)$ | The bipartite mapping graph. |
| $w(e) \in [0, 1]$ | Confidence weight on a mapping edge. |
| $\theta_{\text{auto}}$ | Auto-accept confidence threshold (configurable). |
| $T_d$, $T_w$ | Daily and weekly time domains. |
| $A: \mathbb{R}^{T_d} \to \mathbb{R}^{T_w}$ | Aggregation operator (daily → weekly). |
| $K$ | Disaggregation kernel (policy-dependent). |
| $a, \alpha$ | `available_cases`, `allocated_cases` from the ERP. |
| $\text{ftp}$ | Free-to-promise function. |
| $\mathcal{S}$ | The order-draft FSM state space. |
| $\delta$ | The FSM transition relation. |

LaTeX renders inline as `$...$` and display as `$$...$$`. GitHub, GitLab, and Obsidian all support this; for VS Code preview, install the Markdown All-in-One extension.

---

## 2. The two primitive spaces and adapters as morphisms

We treat the system as two object-classes connected by morphisms:

$$
\mathcal{P}_{\text{CPG}} \xrightarrow{\;\;\Phi\;\;} \mathcal{P}_{\text{normalized}} \xrightarrow{\;\;\Psi\;\;} \mathcal{P}_{\text{ERP}}
$$

- $\mathcal{P}_{\text{CPG}}$ is the space of retailer-published facts. Each retailer publishes into its own subspace with its own basis (different time grain, location grain, units). Concretely, an element of $\mathcal{P}_{\text{CPG}}$ is a row of a retailer CSV.
- $\mathcal{P}_{\text{normalized}}$ is the canonical-entity space. Elements are `CanonicalDemandLine`, `CanonicalActualsLine`, `RetailerProductKey`, `MappingResult`, `FulfillmentClassification` — all in a single uniform basis (ISO week, ERP-resolved SKU, cases).
- $\mathcal{P}_{\text{ERP}}$ is the space of ERP API state — products, customers, warehouses, inventory, open orders, drafts.
- $\Phi$ is the **retailer adapter** — a family of morphisms parameterized by the retailer spec (per **D-001**): one $\Phi_{\text{Tesco}}$, one $\Phi_{\text{Sainsburys}}$, etc. Each $\Phi_r$ is the composition of three sub-morphisms (entity resolution, demand alignment, classification) defined in §§3–5.
- $\Psi$ is the **draft-emission morphism** — converts `Safe`-classified normalized lines to `OrderDraftRequest` payloads bound for the ERP. Side-effecting at the boundary.

> **Engineering vs mathematical adapters.** Gemini's "RetailerAdapter base class with `normalize_forecast()` / `normalize_epos()` methods" describes one *implementation* of $\Phi_r$ — subclass-per-retailer. We choose the *config-driven* implementation under **D-001**. The morphism formalism is independent of the choice; the implementation is downstream.

Composition $\Psi \circ \Phi_r$ is the end-to-end pipeline for retailer $r$. The pipeline is *deterministic* given a fixed snapshot of ERP state; this lets us reason about replay and idempotency (§7).

---

## 3. Entity resolution as stratified bipartite matching

### 3.1 Bipartite graph with weighted edges

For each entity kind (products, locations), the retailer-to-ERP mapping is a bipartite graph

$$
G = (V_R \cup V_E,\ E),\qquad E \subseteq V_R \times V_E,\qquad w: E \to [0, 1]
$$

with the disjointness $V_R \cap V_E = \emptyset$ and the constraint that for each $v \in V_R$ at most one outgoing edge is auto-accepted (the resolver is *deterministic* in the auto-accept band, even when the candidate set has cardinality $> 1$).

### 3.2 Stratified evidence — the resolver as priority cascade

Edges are not generated by a single procedure. The resolver is a priority-ordered cascade

$$
E_1 \succ E_2 \succ E_3 \succ E_4
$$

where each $E_k$ is a relation $V_R \rightharpoonup V_E$ (partial function) producing edges with confidence in a stratum $[\underline{w}_k, \overline{w}_k]$. For the product-resolution problem the cascade is:

| Stratum | Codebase identifier | Generator | Confidence stratum |
|---|---|---|---|
| $E_1$ | `gtin_current` | Exact match on `current_gtins` | $[0.95,\ 1.0]$ |
| $E_2$ | `gtin_legacy` | Exact match on `legacy_gtins` | $[0.85,\ 0.95]$ |
| $E_3$ | `alias_exact` | Exact match on `aliases` | $[0.70,\ 0.85]$ |
| $E_4$ | `fuzzy_jw` | Fuzzy match on canonicalized `name` | $[0.30,\ 0.70]$ |

> **Notation note (per D-018).** The formalism uses legacy notation $E_1$–$E_4$ in mathematical expressions; codebase identifiers use semantic names (`gtin_current`, `gtin_legacy`, `alias_exact`, `tfidf_overlap`, `fuzzy_jw`, `llm_augmented`). See the mapping table in [DECISIONS.md D-018](../../DECISIONS.md).

The resolver fires the *first* stratum that produces a candidate; later strata are not consulted for that retailer key.

Cross-checks (e.g., temperature-band consistency between retailer-declared and mapped-ERP-product) apply a multiplicative penalty $\lambda \in (0, 1]$ to the assigned confidence:

$$
w(e) \leftarrow \lambda \cdot w(e)
$$

A band mismatch sets $\lambda$ small enough to drop the edge below $\theta_{\text{auto}}$ (high-precision "mapping wrong" signal — fixture gotcha #4).

### 3.3 Three review states (correcting Gemini)

Gemini described "ambiguous mappings" as either unconnected vertices or low-weight edges. These are operationally distinct:

$$
\textit{state}(v) = \begin{cases}
\textit{Resolved} & \text{if } \exists e = (v, \cdot) \in E,\ w(e) \geq \theta_{\text{auto}} \\
\textit{NeedsVerification} & \text{if } \exists e = (v, \cdot) \in E,\ w(e) < \theta_{\text{auto}} \\
\textit{Unmapped} & \text{if } \nexists e = (v, \cdot) \in E
\end{cases}
$$

`NeedsVerification` shows the operator a candidate and asks "yes/no". `Unmapped` shows the operator a retailer line and asks them to *create* a mapping. The review surface treats these as separate widgets.

### 3.4 The `MappingResult` carries provenance

Each emitted mapping is a triple

$$
\textit{MappingResult} = \langle e \in E,\ w(e),\ \textit{evidence}(e) \rangle
$$

where $\textit{evidence}(e)$ records *which stratum fired* and *what value matched*. Provenance is a first-class output, not a debug aid.

### 3.5 Confidence calibration (per D-011, fully locked across iterations 5, 8, 9)

#### 3.5.1 Per-match scoring at trial scope (locked)

For exact-match strata, use the **Fellegi-Sunter (1969) framework** with unsupervised priors. Let $K_x$ be the count of distinct ERP SKUs sharing the matched key $x$ (the empirical $u$-probability):

$$
\begin{aligned}
w_1(x) &= \frac{1 - \epsilon}{K_x} && \text{(stratum } E_1\text{: current\_gtins)} \\
w_2(x) &= (1 - \gamma) \cdot \frac{1 - \epsilon}{K_x} && \text{(stratum } E_2\text{: legacy\_gtins)} \\
w_3(x) &= \frac{1 - \epsilon}{K_x^{\alpha}} && \text{(stratum } E_3\text{: aliases)}
\end{aligned}
$$

Hyperparameters with default initial values (treat as starting points pending labeled-data tuning): $\epsilon = 0.02$ (data-corruption prior), $\gamma = 0.10$ (obsolescence rate), $\alpha = 1.5$ (alias dampening exponent).

For the fuzzy stratum, use Jaro-Winkler² on canonicalized strings:

$$w_4(x) = \mathrm{JW}(x)^2$$

JW is canonical for short record-linkage because it weights prefix matches heavily — appropriate for SKU strings where brand/category tokens lead. The squaring suppresses mid-tier matches and creates contrast between true matches and noise.

**Why this is materially better than static bands.** A colliding `current_gtin` (e.g., $K_x = 2$) yields $w_1 = 0.49$ — automatically falling out of any auto-allocate threshold without manual band-tuning. A generic alias ("Spicy Chorizo" on $K_x = 3$ SKUs) yields $w_3 \approx 0.18$ under the dampening exponent, demanding review. The data does the band-tuning.

#### 3.5.2 The cascade is a discovery heuristic, not a band constraint (per iteration 9)

The cascade $E_1 \succ E_2 \succ E_3 \succ E_4$ governs discovery order — which stratum fires first, with lower strata preempted on a hit. It does **not** constrain score values. An exceptionally clean $E_4$ match can legitimately score above an ambiguous $E_3$ match; that's the system reporting what the data says.

#### 3.5.3 Production calibration: Cascaded Classification

With a labeled stream of operator review resolutions ($N \gtrsim 200$), upgrade to **Cascaded Classification** — a single LR over the per-match score plus a stratum-indicator and additional features:

$$P(\text{Match} = 1 \mid e) = \sigma\!\left( w_0 + w_1 \cdot \text{Score}(e) + \sum_k \beta_k \cdot I_k(e) + \beta_{\mathrm{JW}} \mathrm{JW}(e) + \beta_{\mathrm{TFIDF}} \mathrm{TFIDF}(e) + \beta_{\deg} \deg(v_R(e)) \right)$$

The model learns negative weights for lower strata ($\beta_4 < \beta_3 < \beta_2 < \beta_1$), preserving expected reliability ordering while allowing data-driven score overlap.

At $N \gtrsim 1000$, separate the combiner from the calibrator and replace LR-as-calibrator with **isotonic regression** (non-parametric, monotonic) for tighter calibration in the score-distribution tails. **Beta calibration** is a parallel option specifically suited to the single-feature path (calibrating $\mathrm{JW}^2$ alone, where the score distribution is heavily skewed and Platt's sigmoid assumption can be off).

#### 3.5.4 Calibration is not strictly required at trial scope

A side-effect of locking the Fellegi-Sunter framework: the per-stratum scores are themselves principled posterior probabilities under the model's assumptions. **At trial scope, no post-hoc calibrator is needed** — the FS posteriors are calibrated by construction. Calibration becomes a production refinement once labeled data accumulates.

#### 3.5.5 Trial-scope nuance on the global tripwire

Gemini iteration 9 says the auto-allocate tripwire becomes a "single global threshold" on confidence once probabilities are calibrated. At trial scope our calibration rests on three unsupervised priors ($\epsilon, \gamma, \alpha$); a single global threshold there is more conservative than at production scope (where labeled data tightens the priors). Treat $\theta_{\text{auto}}$ as `provisional` and operator-tunable until $\sim 200$ resolutions accumulate.

---

## 4. Demand alignment as change-of-basis

### 4.1 The asymmetry that the Gemini tensor framing elided

Gemini's $D \in \mathbb{R}^{S \times L \times T}$ implies a single shared basis. The actual problem is that **retailers publish into incompatible bases**, and aligning them requires explicit linear maps in *both* directions.

### 4.2 Time-grain alignment

Let $T_d$ be the daily time domain (Monday 1 through Sunday 7 of an ISO week, indexed) and $T_w$ the weekly time domain. Define the **aggregation operator**

$$
A \in \{0, 1\}^{|T_w| \times |T_d|},\qquad A_{w,d} = \begin{cases} 1 & \text{if day } d \in \text{week } w \\ 0 & \text{otherwise} \end{cases}
$$

For a daily demand vector $d \in \mathbb{R}^{|T_d|}$, the weekly aggregate is $A d \in \mathbb{R}^{|T_w|}$. **Aggregation is total-preserving**: $\mathbf{1}^T (A d) = \mathbf{1}^T d$ because each column of $A$ has exactly one $1$.

### 4.3 Disaggregation as policy-driven inverse

The map $A$ is *not* invertible — it has a non-trivial null space (any redistribution of total within a week sums to the same weekly total). To go from weekly back to daily we choose a **disaggregation kernel** $K \in \mathbb{R}_{\geq 0}^{|T_d| \times |T_w|}$ satisfying

$$
A K = I_{|T_w|}
$$

(the right-inverse condition: round-trip weekly → daily → weekly is the identity on weekly). The columns of $K$ encode the policy.

> **Categorical interpretation.** $A$ has many right-inverses; the system commits to one $K$ per retailer-context but tags every disaggregated value with the kernel that produced it.

Sainsbury's data is published in $\mathbb{R}^{|T_w|}$; Tesco's in $\mathbb{R}^{|T_d|}$. The "compare next week" tool always operates in $\mathbb{R}^{|T_w|}$ (use $A$ on Tesco; pass through Sainsbury's). Any *daily* claim derived from Sainsbury's is $K$-derived and carries `inferred = true`.

#### 4.3.1 Default kernel (per D-009, locked)

For a retailer with no historical EPOS, the default day-of-week kernel is the **config-declared static UK-grocery DOW profile**:

$$K_{\text{default}} = [0.10,\ 0.10,\ 0.10,\ 0.15,\ 0.25,\ 0.20,\ 0.10]^T \quad (\text{Mon} \to \text{Sun})$$

Per-retailer override allowed in the adapter spec. **Uniform $K = 1/7$ is operationally dangerous** — it triggers false stockouts early in the week and hides them late in the week (grocery sales heavily skew Thu/Fri/Sat) — and is rejected as a default.

#### 4.3.2 Production: simplex-constrained NNLS

With ≥ ~26 weeks of labeled per-day actuals $D^{\text{actual}} \in \mathbb{R}_{\geq 0}^{|T_d| \times N}$ and weekly aggregates $D^{\text{weekly}} = A \cdot D^{\text{actual}}$, learn $K$ as the simplex-constrained least-squares optimizer with optional Laplacian smoothing:

$$
\min_{K \geq 0,\ \mathbf{1}^T K = \mathbf{1}^T} \;\; \big\| K \cdot D^{\text{weekly}} - D^{\text{actual}} \big\|_F^2 + \lambda \big\| L K \big\|_F^2
$$

where $L$ is the discrete Laplacian on adjacent days. The constraint $\mathbf{1}^T K = \mathbf{1}^T$ ensures column-stochasticity, satisfying $A K = I_{|T_w|}$ exactly. Per Gemini iteration 6 (Denton/Chow-Lin lineage in econometrics): **don't parameterize on covariates** at small $N$ — week-of-year affects weekly volume not the DOW distribution, and identifiability collapses with small samples.

### 4.4 Location-grain alignment

The same structure applies to locations. Let $L_{\text{depot}}$ be the per-depot location domain and $L_{\text{aggregate}}$ the "All Depots" domain (with $|L_{\text{aggregate}}| = 1$ in the simplest case but can be larger if "regional aggregate" is published).

Tesco publishes in $L_{\text{depot}}$; Sainsbury's publishes in $L_{\text{aggregate}}$. Aggregation $L_{\text{depot}} \to L_{\text{aggregate}}$ is total-preserving and invertible only modulo a depot-allocation kernel.

For "compare next week" we **operate in $L_{\text{aggregate}}$ for Sainsbury's by default**, only fanning out to depots when an operator commits to a kernel.

### 4.5 Unit alignment

Cases vs consumer units. For SKU $s$ with `case_pack` $c_s \in \mathbb{Z}_{\geq 1}$, the unit-to-case map is the *ceiling* division

$$
\textit{cases}(u) = \left\lceil u / c_s \right\rceil
$$

The ceiling reflects the operational reality of integer cases, and introduces a small over-fulfillment bias the system tracks. **Size-unit canonicalization** (`0.5kg` $\to$ `500g`) is a *separate* prior pass on the name-canonicalization side; do not conflate the two.

---

## 5. Allocation as constrained linear system

### 5.1 Free-to-promise

For an SKU $s$, time window $W$, and retailer $r$:

$$
\text{ftp}(s, W, r) \;=\; \underbrace{\sum_{w \in \mathcal{W}_{\text{compat}}(s)} \bigl( a(s, w) - \alpha(s, w) \bigr)}_{\text{compatible-warehouse net inventory}} \;-\; \underbrace{\sum_{o \in \mathcal{O}(r, s, W)} q(o)}_{\text{committed open orders}}
$$

with $\mathcal{W}_{\text{compat}}(s) = \{ w : \texttt{temperature\_band}(w) = \texttt{temperature\_band}(s) \}$.

This **closes the gap** in [`working-doc.md`](../process/working-doc.md) Design gaps vs README evaluation criteria #4 (FTP math needs to be pinned down).

### 5.2 Classification predicate

For a retailer demand $d_r(s, W)$:

$$
\textit{class}(s, W, r) = \begin{cases}
\textit{Safe} & \text{if } \text{ftp}(s, W, r) \geq d_r(s, W) \\
\textit{AtRisk} & \text{if } 0 \leq \text{ftp}(s, W, r) < d_r(s, W) \\
\textit{Blocked} & \text{if mapping unresolved or low-confidence}
\end{cases}
$$

`Blocked` is *upstream* of FTP — we cannot evaluate the inequality if the mapping itself is undefined. Implementation runs §3 first.

### 5.3 The supply-constrained case (per D-010, locked)

When $\sum_r d_r(s, W) > s$, multiple retailers are competing. The allocation vector $x \in \mathbb{R}^n$ (indexed by retailer) lies in the polytope

$$
\Pi = \Bigl\{ x \in \mathbb{R}^n_{\geq 0} \;:\; \sum_{i=1}^n x_i \leq s,\ x_i \leq d_i \ \forall i \Bigr\}
$$

#### 5.3.1 Default objective: pro-rata

$$
x_i = d_i \cdot \frac{s}{\sum_j d_j}
$$

Locked as the default for CPG. Identical fill rates across retailers; hyperparameter-free; trivially explainable. Standard OR / contract-law pattern.

#### 5.3.2 Weighted generalization: water-filling

Per-retailer priority weights $\rho_i \in \mathbb{R}_{\geq 0}$ generalize pro-rata via a **water-filling algorithm**. The closed-form heuristic $x_i = (\rho_i d_i) \cdot s / \sum_j (\rho_j d_j)$ is **unsafe** — it can violate $x_i \leq d_i$ under skewed $\rho$ (Gemini iteration 7 caught this; pushback §8.8 below). The water-filling procedure:

1. Set $r_i = \rho_i \cdot d_i$ as the *unfrozen* allocation rate.
2. Allocate continuously: $x_i = \min(d_i,\ s \cdot r_i / \sum_{j \in U} r_j)$ where $U$ is the set of unfrozen retailers.
3. When any $x_i$ hits $d_i$, freeze that index, subtract $d_i$ from the remaining supply, and recurse on $U \setminus \{i\}$.

Pro-rata is the special case $\rho \equiv 1$ with no freezing (since $\sum d_i > s$ implies all $x_i < d_i$).

#### 5.3.3 Auto-vs-review tripwire: fill-rate thresholding

Define $\tau_{\text{safe}}$ (config-declared, default $0.90$). The classification predicate extends to:

$$
\textit{class}(s, W) = \begin{cases}
\textit{Safe} & \text{if } \text{ftp}(s, W) \geq \sum_r d_r(s, W) \\
\textit{AtRisk} & \text{if } \tau_{\text{safe}} \leq \frac{\text{ftp}(s, W)}{\sum_r d_r(s, W)} < 1 \quad \text{(auto-allocate per } 5.3.1/2\text{)} \\
\textit{AtRisk\_Severe} & \text{if } \frac{\text{ftp}(s, W)}{\sum_r d_r(s, W)} < \tau_{\text{safe}} \quad \text{(human review)} \\
\textit{Blocked} & \text{if mapping unresolved}
\end{cases}
$$

The boundary $\tau_{\text{safe}}$ is the canonical OR / SLA framework. **Value, not pattern, is configurable** — the math doesn't fix a number; commercial judgment does.

---

## 6. Workflow — FSM and DAG, interlocked

### 6.1 The order-draft FSM

State space $\mathcal{S}$ and transitions $\delta \subseteq \mathcal{S} \times \mathcal{S}$:

$$
\mathcal{S} = \{\textit{New},\ \textit{Resolved},\ \textit{Classified},\ \textit{Drafted},\ \textit{Blocked},\ \textit{Reviewing}\}
$$

Each transition $(s_1, s_2) \in \delta$ has a guard predicate $g_{s_1 \to s_2}: (\textit{DAG outputs}) \to \{\bot, \top\}$. Sample guards:

| Transition | Guard |
|---|---|
| $\textit{New} \to \textit{Resolved}$ | $\exists e \in E, w(e) \geq \theta_{\text{auto}}$ |
| $\textit{Resolved} \to \textit{Classified}$ | $\text{ftp}$ has been computed for this $(s, W)$ |
| $\textit{Classified} \to \textit{Drafted}$ | $\textit{class} = \textit{Safe} \wedge \texttt{operator\_optin\_autodraft}$ |
| $\textit{Classified} \to \textit{Reviewing}$ | $\textit{class} = \textit{AtRisk}$ |

The transitions are **deterministic** — each guard is a function of fully-observed inputs. Markov-chain modelling does *not* apply here (correcting Gemini's universal-discard framing only by virtue of also rejecting Markov for *this* component, but for the right reason — see §8).

### 6.2 The compute DAG

The pipeline is a fixed DAG $G_{\text{compute}}$ with nodes for `load_*`, `resolve_mappings`, `compute_ftp`, `classify_lines`, `route_to_state`. Edges encode data dependency. The DAG is *acyclic* and node functions are *pure* — no shared mutable state.

A canonical run executes nodes in topological order, parallelizing where independent. The output of `route_to_state` is the per-tuple final FSM state.

### 6.3 The interlock

The structural fact Gemini's parallel framing missed: **FSM transition guards consume DAG outputs**. The FSM is not a separate stochastic process; it's a deterministic post-processing step on the DAG's outputs. Formally, if $\Omega$ denotes DAG outputs and $\delta(\cdot \mid \Omega)$ denotes the FSM transition relation parameterized by $\Omega$, the runtime semantics is

$$
(\textit{state}_{\text{out}})_i \;=\; \delta\bigl( \textit{state}_{\text{in}})_i \,\big|\, \Omega \bigr)
$$

for each tuple $i$. There is no stochastic element; given $\Omega$, $\textit{state}_{\text{out}}$ is determined.

---

## 7. Idempotency

The single side-effecting operation is `create_draft: \textit{ref} \times \textit{payload} \to \textit{ERP state}$. The ERP guarantee:

$$
\textit{create\_draft}(\textit{ref},\, p) \circ \textit{create\_draft}(\textit{ref},\, p) \;=\; \textit{create\_draft}(\textit{ref},\, p)
$$

To make the guarantee *useful*, we derive $\textit{ref}$ deterministically from the upstream key:

$$
\textit{ref}(r, s, W, \ell) \;=\; \mathrm{sha256}\bigl( r \,\|\, s \,\|\, W \,\|\, \ell \bigr)
$$

where $r$ is the retailer code, $s$ is the resolved ERP `sku`, $W$ is the ISO week, $\ell$ is the resolved `ship_to_location_id`. This makes the entire pipeline retry-safe: a partial failure mid-pipeline can be re-run without producing duplicate drafts.

> **Categorical interpretation.** This is a *natural transformation* condition on the side-effecting boundary: the pipeline-as-functor commutes with self-composition modulo equality of `external_reference`. Phrased less categorically: same input gives same output, even when the output is "create a draft".

Empirically confirmed: `tests/erp/test_client.py::test_create_order_draft_is_idempotent` exercises the guarantee against the live ERP and verifies $\textit{draft\_id}$ stability under re-POST.

---

## 8. Where this diverges from the Gemini source, and why

These are deliberate departures from [`raw-truth.md`](../process/raw-truth.md). Each is logged here so future iterations don't accidentally re-introduce a Gemini point we've already decided against.

### 8.1 Markov chains are not fully discarded

**Gemini:** "Markov Chains (Discard). Order fulfillment and supply chain reconciliation are not stochastic processes."

**Our position:** Discard for **workflow** (the FSM is deterministic). Reserve for **forecast drift detection** — EPOS-vs-forecast residuals are a noisy signal and signal-detection / Markov-style transition models are appropriate there. The full discard is too sweeping by one component. **D-024 implements this**: a 3-state Markov chain over per-SKU residual histories with persistence and divergence signals.

### 8.2 Adapter shape: morphism formalism, config-driven implementation

**Gemini:** "Implement a base `RetailerAdapter` interface with methods like `normalize_forecast()` and `normalize_epos()`. Concrete classes like `TescoAdapter` ingest the specific CSV shape."

**Our position:** Adapters are *morphisms* $\Phi_r$ in the formalism (§2). The *implementation* of those morphisms is config-driven per **D-001** — one YAML/Pydantic spec per retailer, parsed by a single resolver, not subclass-per-retailer. The math doesn't dictate the implementation; the README's 2 → 200 customer scaling criterion does.

### 8.3 Bipartite mapping with stratified evidence (not a flat graph)

**Gemini:** "$G = (V_R \cup V_E, E)$ where edges represent valid mappings. Ambiguous mappings are unconnected vertices or edges assigned a confidence weight $w < 1$."

**Our position:** The graph has a richer structure. Edges are produced by a *priority-ordered cascade* of generators ($E_1 \succ E_2 \succ E_3 \succ E_4$) each with its own confidence stratum. Provenance is a first-class output. The state space is *three-valued* — `Resolved`, `NeedsVerification`, `Unmapped` — not two. See §3.

### 8.4 Demand alignment is change-of-basis, not tensor reshape

**Gemini:** "Demand is a tensor $D \in \mathbb{R}^{S \times L \times T}$."

**Our position:** Each retailer publishes into its own basis with its own time/location/unit grain. Aligning to a canonical basis requires explicit aggregation operators ($A$) and disaggregation kernels ($K$). Aggregation is total-preserving; **disaggregation is policy-driven and lossy**. The single-tensor framing hides the asymmetry that determines what claims the system can defensibly make. See §4.

### 8.5 Allocation: temperature/warehouse partitioning is load-bearing

**Gemini:** "$\sum x_i \leq s$, $0 \leq x_i \leq d_i$" (LP without further structure).

**Our position:** $s$ is not scalar — it's per (sku, warehouse), and warehouses partition by `temperature_band`. The LP must respect compatibility. Open-order subtraction is a separate term. See §5.

### 8.6 FSM and DAG interlock; they're not parallel structures

**Gemini:** Described FSM and DAG side-by-side, suggesting two parallel structures.

**Our position:** They interlock. FSM transition guards consume DAG outputs. The runtime is *first DAG, then FSM*, not the two in parallel. See §6.3.

### 8.7 Idempotency stated as a structural condition

**Gemini:** Mentioned the API doc's idempotency note implicitly via the "Reusing the same external_reference" phrasing.

**Our addition:** State it as a structural condition on the side-effecting morphism (§7) and derive `external_reference` deterministically to make the condition load-bearing. Empirically confirmed in tests.

### 8.8 Closed-form weighted allocation is unsafe; use water-filling

**Gemini:** Caught and rejected the heuristic $x_i = (\rho_i \cdot d_i) \cdot s / \sum_j (\rho_j \cdot d_j)$ that I had floated in the iteration-3 prompt — it can violate the upper-bound constraint $x_i \leq d_i$ when $\rho$ is heavily skewed and supply is high.

**Our position:** Agreed. **Water-filling** (allocate continuously, freeze on cap-hit, redistribute) is the rigorous unification. Pro-rata is the special case $\rho \equiv 1$. See §5.3.2.

### 8.9 Tripwire value is config, not constant

**Gemini:** Recommended hardcoding $\tau_{\text{safe}} = 0.90$ "to demonstrate to reviewers that you understand the boundary".

**Our position:** Lock the *pattern* (fill-rate thresholding) as the canonical OR/SLA framework. The *value* is a commercial-judgment call, not a mathematical one — leave it config-declared with $0.90$ as a sensible default. The "demonstrate to reviewers" justification is a presentation argument that doesn't survive past the trial. See §5.3.3.

### 8.10 Bands for exact-match strata — resolved via Fellegi-Sunter

**Gemini iteration 5:** Did not address how to derive $[\underline{w}_k, \overline{w}_k]$ for $E_1, E_2, E_3$, despite the prompt asking. Only addressed the fuzzy stratum.

**Iteration 8 resolution:** Per the Fellegi-Sunter (1969) framework, the bands themselves are abandoned; per-match scores are dynamic posteriors driven by collision counts $K_x$ and three unsupervised priors. See §3.5.1 for formulas.

**Pushback / nuance worth recording:** The hyperparameters $\epsilon, \gamma, \alpha$ are themselves unsupervised priors — vibes-y at a higher abstraction layer. We've reduced the vibes surface from 8 numbers (4 stratum bands × 2 endpoints) to 3 hyperparameters; that's a real principled improvement, but not vibes-free. The dampening exponent $\alpha = 1.5$ for aliases is justified intuitively (aliases are inherently fuzzier than GTINs) but not derived. Once $\sim 200$ labels accumulate, all three become learnable from the supervised review-resolution stream.

### 8.11 Cascade as blocking strategy, not band constraint (drop strict bands)

**Gemini iteration 9:** "Drop the strict-band model entirely. The cascade $E_1 \succ E_2 \succ E_3 \succ E_4$ is a *blocking strategy* (discovery order), not a score constraint. Each stratum scores on its own merit. Standard framing: **Cascaded Classification** in record-linkage literature."

**Our position:** Agreed and locked. Bands are abandoned; the cascade is preserved purely as the discovery heuristic (which stratum fires first, with lower strata preempted on a hit). Score is independent of stratum-of-origin; lineage and confidence are surfaced as orthogonal fields in the operator UI.

**One pushback worth recording:** Gemini says the auto-allocate tripwire becomes a "single global threshold" on confidence. **This is true at production scope** (after supervised LR has produced calibrated probabilities), **not at trial scope** (where scores are only crudely calibrated — Jaro-Winkler² for fuzzy, collision-rate-baseline for exact pending follow-up A). At trial scope a single global threshold is more conservative than at production scope; treat $\theta_{\text{auto}}$ as `provisional` and operator-tunable until calibration data accumulates. See §3.5 (production calibration path).

---

## 9. Open questions

Status legend: ✅ resolved · 🟡 partially resolved · ⏳ still open.

1. ✅ **Confidence calibration.** Resolved by D-011 (Jaro-Winkler² for $E_4$, Platt scaling at $N \gtrsim 200$ for production). Two sub-gaps remain (band derivation for $E_1$/$E_2$/$E_3$; cascade-band consistency under JW²) — tracked under MATH-SOT-IT3, still open.

2. ✅ **Drift detection as signal-detection.** Trial-scope answer locked by **D-012**: lagged-actuals plausibility check (ratio $\rho = f_{t+1} / \max(a_t, 1)$ with thresholds $[0.5, 1.5]$, promo-segmented). See §10. **D-020** adds a classical residual mode ($r = a_t - f_t$, same-period) via the strategy pattern. **D-024** implements Markov regime-detection over multi-week residual histories (3-state transition matrix, persistence + divergence signals, context hierarchy pattern). All three modes are live via `DriftAnalyzer`.

3. ✅ **Allocation policy under supply constraint.** Resolved by D-010 (pro-rata default; water-filling for weighted; fill-rate thresholding tripwire with config $\tau_{\text{safe}}$). See §5.3.

4. ✅ **The disaggregation kernel as a learned object.** Resolved by D-009 (static UK-grocery DOW profile default for trial; simplex-constrained NNLS with optional Laplacian smoothing for production at ≥ ~26 weeks of data). See §4.3.

5. ⏳ **Polymorphism vs morphism (revisit D-003).** Now that the morphism formalism is on paper, re-examine whether Pydantic-class polymorphism for `MappingResult` etc is the right *implementation* of the morphism object. Tentative answer: yes — Pydantic classes are a fine concrete realization of morphism domains/codomains, and config-driven specs are a fine concrete realization of the morphism *parameters*. But this should be revisited explicitly when canonical entities land.

6. ✅ **Sub-gap from D-011 (a): exact-match baseline scores.** Resolved by Gemini iteration 8 via Fellegi-Sunter framework. Per-stratum scores are dynamic posteriors driven by collision counts $K_x$ and three unsupervised priors ($\epsilon, \gamma, \alpha$). See §3.5.1.

7. ✅ **Sub-gap from D-011 (b): cascade-band consistency.** Resolved by Gemini iteration 9: drop strict bands; cascade is a *blocking strategy*, scoring is independent. Production calibrator is **Cascaded Classification** (LR over score + stratum-indicator). Lineage and confidence are surfaced as orthogonal UI fields. See §3.5.2 and §8.11.

---

## 10. Drift detection (trial-scope: lagged-actuals plausibility check)

Locked by **D-012**. The fixture provides a forward-week forecast (W20) and a *prior*-week EPOS actuals (W19), but no forecast for the same period as the actuals. Classical drift detection — residual = forecast − actuals over the same window — is therefore unreachable at trial scope. We implement a recency-baseline diagnostic instead.

### 10.1 The lagged-actuals ratio

For a Resolved (retailer, sku) pairing, with forecast eaches at period $t+1$ and lagged actuals eaches at period $t$:

$$
\rho_{t+1} \;=\; \frac{f_{t+1}}{\max(a_t,\ 1)}
$$

The denominator clamp avoids division-by-zero on stockout weeks; signal-stream consumers should treat $a_t = 0$ specially (the system tags such cases with a known-unknown reason rather than a numeric flag).

### 10.2 Threshold gating

Direction is determined by a two-sided threshold $[\tau_{\text{low}}, \tau_{\text{high}}]$ (defaults $[0.5, 1.5]$, configurable):

$$
\textit{direction}(\rho) = \begin{cases}
\textit{low}  & \text{if } \rho < \tau_{\text{low}} \\
\textit{high} & \text{if } \rho > \tau_{\text{high}} \\
\textit{ok}   & \text{otherwise}
\end{cases}
$$

### 10.3 Promo segmentation

Forecast rows with `promo_flag = True` are excluded from threshold-flagging because promo creates expected uplift unrelated to baseline drift. Formally, the gate is multiplicative on the threshold check:

$$
\textit{direction}_{\text{flagged}}(\rho, \pi) \;=\; \begin{cases}
\textit{ok} & \text{if } \pi = \mathrm{True}\ (\textit{promo segmented}) \\
\textit{direction}(\rho) & \text{otherwise}
\end{cases}
$$

where $\pi = \mathbb{1}[\text{promo}_{t+1}]$. The signal record carries both `promo_flag` and `promo_segmented` so operators can see the gate fired.

**Retailer asymmetry.** Tesco publishes `promo_flag` per row; Sainsbury's does not. For Sainsbury's, $\pi$ is always False with a known-unknown caveat in the reason text. We do not infer promo state for retailers that don't publish it.

### 10.4 Beyond point-in-time: regime detection

The plausibility and residual modes are point-in-time diagnostics. **D-024** adds a Markov regime-detection mode that models per-SKU residual histories as a discrete-state stochastic process:

- **State space:** $S = \{\text{accurate}, \text{over\_forecast}, \text{under\_forecast}\}$, discretized using `residual_threshold`.
- **Transition matrix:** Empirical 3×3 matrix with Laplace smoothing: $p_{ij} = (c_{ij} + 1) / (c_i + |S|)$.
- **Persistence signal:** SKU stuck in non-accurate state for $k \geq$ threshold consecutive weeks; probability $p_{ss}^k$.
- **Divergence signal:** KL divergence between per-SKU stationary distribution and population-level matrix.

Architecture uses **Option C (context hierarchy)**: `MarkovDriftContext(DriftContext)` carries `residual_history` without polluting the base context. Future strategies follow the same subclass pattern.

> **D-020 addendum:** A `residual` strategy is available alongside the plausibility check. When same-period forecast + actuals CSVs exist, `analyze_drift(mode="residual")` computes $r = a_t - f_t$ with a configurable percentage-error threshold (`drift_residual_threshold`, default 10%). After each residual run, results are written to the Repository for automatic Markov history accumulation.

### 10.5 Mapping flow

Forecast lines whose mapping is `Blocked` or `NeedsVerification` are not turned into signals — they're counted under `summary["skipped_unmapped"]` to keep the signal stream clean while preserving the volume of un-comparable lines.

Cross-references: `src/cpg_reconciler/drift/` (module), `src/cpg_reconciler/drift/markov.py` (TransitionMatrix, MarkovDriftContext, markov_strategy), `src/cpg_reconciler/pipeline/drift.py` (entry-point), `tests/drift/test_baseline.py` (plausibility + infrastructure tests), `tests/drift/test_residual.py` (residual mode tests), `tests/drift/test_markov.py` (Markov mode tests, 45 tests).

---

## 11. References

- [`raw-truth.md`](../process/raw-truth.md) — Gemini conversation transcripts (source).
- [`primitives/CPG/`](../../primitives/CPG/) — conceptual ontology, cross-references this doc.
- [`primitives/ERP/`](../../primitives/ERP/) — grounding context, out of operational scope per **D-005**.
- [`docs/architecture/cpg-reconciler-problem-entity-model.md`](cpg-reconciler-problem-entity-model.md) — entity model.
- [`docs/architecture/storage-runtime-decision.md`](storage-runtime-decision.md) — Polars + DuckDB decision.
- [`DECISIONS.md`](../../DECISIONS.md) — chronological decision log.
