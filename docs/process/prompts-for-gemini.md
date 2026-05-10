# Prompts for Gemini — MATH-SOT iteration #2

Three pasteable prompts, one per open mathematical thread surfaced in [`docs/architecture/formalism.md`](../architecture/formalism.md) §9. Each is self-contained enough to drop into a fresh conversation and tight enough that it won't sprawl.

After Gemini responds, paste the answers into [`raw-truth.md`](raw-truth.md) as Iteration 5 / 6 / 7 (one per thread), and ping me to integrate.

---

## Prompt 1 — Confidence calibration

```
Context: I'm building an entity-resolution layer between retailer-published SKUs and ERP-canonical SKUs as a bipartite mapping graph G = (V_R ∪ V_E, E) with confidence weights w(e) ∈ [0, 1]. Edges are produced by a priority-ordered cascade:

  E_1 (exact match on current_gtins)   →  band [0.95, 1.00]
  E_2 (exact match on legacy_gtins)    →  band [0.85, 0.95]
  E_3 (exact match on aliases)         →  band [0.70, 0.85]
  E_4 (fuzzy match on canonical name)  →  band [0.30, 0.70]

These bands are vibes-based. I want them to mean something.

Question: how should the confidence weights be principled?

Specifically:

1. For an exact match in stratum E_k (k ∈ {1,2,3}), is there a defensible derivation of the band from the matching procedure itself — e.g., from observed alias-overlap statistics in the ERP master, or from ambiguity-density at each rung — without requiring labeled review outcomes?

2. For fuzzy matches in E_4, what's the right shape for w as a function of string distance? I'm aware of normalized Levenshtein, Jaro-Winkler, embedding cosine — but which calibrates against what reference distribution?

3. Once we have a labeled stream of operator review resolutions (yes/no per surfaced candidate), what is the minimum-data path from band-based to learned calibration? Isotonic regression on the resolution log? Platt scaling? Beta calibration? At what dataset size does each start paying off?

4. We're in an 8-hour build with no labels yet, only ~12 SKUs × 2 retailers of fixture data. What's the most rigorous thing we can ship now that isn't vibes?

Please avoid: vague "use a probability" framing without specifying the data-generating process; supervised-only solutions with no bootstrap path; surveys.

Output format: a numbered list of 3-4 distinct options with their tradeoffs (data requirements, theoretical guarantees, operational complexity), plus your specific pick for trial scope and your specific pick for post-trial production scope.
```

---

## Prompt 2 — Disaggregation kernel learning

```
Context: I have an aggregation operator A ∈ {0,1}^(|T_w| × |T_d|) where A_{w,d} = 1 iff day d falls in week w. Tesco publishes daily forecasts; the rollup is

  weekly = A · daily

which is total-preserving and lossless.

The reverse direction is the problem. Sainsbury's publishes weekly aggregates with "All Depots" (single aggregated location). Sometimes I need per-day or per-depot estimates downstream. This requires a disaggregation kernel K with

  A · K = I_{|T_w|}    and    K ≥ 0  (entry-wise)

so that round-trip weekly → daily → weekly is the identity. K has multiple right-inverses; choosing one is choosing a policy.

Currently K is hand-specified per retailer with three default options:
  - uniform: K_{d,w} = 1/7 for d ∈ w
  - EPOS-historically-weighted: K_{d,w} = epos_share(d, w)
  - assign-to-primary-day: K is one-hot on the historical peak day

Question: how should K be learned, and at what data scale does learning become appropriate?

Specifically:

1. With labeled per-day actuals D^actual ∈ R^(|T_d| × N) over N historical weeks and weekly aggregates D^weekly = A · D^actual, the natural problem is

   min_{K ≥ 0, AK = I}  || K · D^weekly − D^actual ||_F^2

   Is this the right formulation? Or does the constraint structure suggest a better one — non-negative least squares (NNLS), simplex-constrained NNLS (column-stochastic K), non-negative matrix factorization with side information, or something I'm missing?

2. Should K depend on covariates (week-of-year seasonality, promo flag, depot temperature band)? A parameterized kernel K(θ; covariates) is more flexible but invites identifiability concerns at small N. What's the right tradeoff?

3. Realistically I have 1 week of EPOS for 2 retailers in the trial fixture. Can I learn anything at that scale, or is the right shipping answer "K is config-declared with sensible defaults; learning is post-trial when a labeled actuals stream exists"?

4. If I can't learn K at trial scale, what's the most defensible *default* K for a CPG-to-retailer setup with no historical EPOS? Uniform feels wrong because demand is rarely uniform across days.

Please avoid: deep models; surveys; ignoring the trial scale constraint.

Output format: 2-3 candidate formulations with explicit tradeoffs, your formal recommendation for trial scope (no labels), and your recommendation for post-trial when ~6 months of EPOS exists.
```

---

## Prompt 3 — Allocation objective under supply scarcity

```
Context: After computing free-to-promise per (sku, window) across temperature-compatible warehouses minus open orders, sometimes total demand exceeds supply: Σ_i d_i > s. The feasible allocation polytope is

  Π = { x ∈ R^n_≥0 : Σ_i x_i ≤ s, x_i ≤ d_i ∀i }

Currently I classify the (sku, window) as "AtRisk" and surface it for human review without auto-allocating — auto-allocation has commercial implications I don't unilaterally make.

I want to define a principled objective for the case where the operator has pre-authorized auto-allocation.

Question: what are the canonical objectives in operations research / supply chain literature for picking x ∈ Π, and what's a sensible default for a CPG-to-retailer setup?

Specifically:

1. Name and formulate the standard objectives I should consider:
   - Proportional / pro-rata: x_i = d_i · (s / Σ d_i)
   - Max-min fair (lexicographic max-min)
   - Weighted-priority: parameterized by per-retailer ρ_i
   - First-come-first-served by required_date
   - Egalitarian (equal allocation, capped at d_i)

   Reference the OR literature each comes from (Bertsimas/Tsitsiklis on LP-based allocation, Roughgarden on fair division, Nash bargaining, etc).

2. For each objective, lay out the *winner profile* — under stress, which retailer profile (small vs large demand, high vs low priority) benefits and which loses?

3. Can these be unified under a single parameterized formulation that takes a per-retailer weight vector ρ ∈ R^n_≥0? E.g., something like x_i = (ρ_i d_i) · s / Σ_j (ρ_j d_j) — does this collapse to pro-rata when ρ is uniform, and to strict priority as ρ becomes lopsided?

4. For a CPG that does NOT have a strong commercial-priority story (every retailer is roughly equal), what's the defensible default?

5. What's the right way to handle the *boundary* between auto-allocation and human review? E.g., auto-allocate when the gap is small (< 10%) but escalate when severe (> 30%) — is there literature on this kind of "auto-with-tripwire" pattern?

Please avoid: "depends on the business" without enumerating the choices; recommending an ML approach without a labeled outcome variable; ignoring the existence of multi-period considerations.

Output format: comparison table (objective, formulation, winner profile, literature reference, suitability for CPG-to-retailer), plus your recommended default with reasoning, plus your recommended escalation tripwire policy.
```

---

## Notes for integrating Gemini's responses

- New chat sections append to [`raw-truth.md`](raw-truth.md) under `## Iteration N` headers (next available is iteration 8).
- Push back on specific Gemini moves that conflict with project commitments; the [`docs/architecture/formalism.md`](../architecture/formalism.md) §8 pattern is the canonical place to capture pushback.
- Update [`primitives/CPG/entity-resolution.md`](../../primitives/CPG/entity-resolution.md), [`primitives/CPG/demand-alignment.md`](../../primitives/CPG/demand-alignment.md), [`primitives/CPG/allocation.md`](../../primitives/CPG/allocation.md) respectively after each thread integrates.
- Add new `D-NNN` entries to [`DECISIONS.md`](../../DECISIONS.md) when each thread reaches a commitment.

---

# Iteration #3 follow-up prompts (D-011 gaps)

After Gemini's iteration 5 response landed, two gaps remained on the confidence-calibration thread. These prompts are scoped tightly to those gaps and assume Gemini has the prior conversation context.

## Follow-up A — exact-match band derivation

```
Context: My priority-ordered cascade for product entity resolution:

  E_1 (exact match on current_gtins)   →  band [0.95, 1.00]
  E_2 (exact match on legacy_gtins)    →  band [0.85, 0.95]
  E_3 (exact match on aliases)         →  band [0.70, 0.85]

Your prior response (iteration 5) addressed E_4 (fuzzy) calibration via
Jaro-Winkler-squared, but didn't address how the bands for the exact-match
strata E_1, E_2, E_3 should be derived from data.

Question: how should the band [w_low, w_high] for each exact-match stratum be
derived from the ERP master itself, without labeled review outcomes?

Specifically:

1. Could we derive the upper bound from the empirical *uniqueness rate* of the
   matching key? E.g.,
     w_high(E_1) = 1.0 − fraction of current_gtins appearing on more than one
                          ERP product (collision rate)
   Is this the right formulation, or does Fellegi-Sunter probabilistic record
   linkage give a tighter answer?

2. Could the lower bound come from a similarly-derived ambiguity-density
   measure, or should it just be `w_high − ε` for some justified ε?

3. Does the same logic apply to legacy_gtins (E_2) — but adjusted for an
   additional "obsolescence" factor (a legacy GTIN might validly identify a
   product that's been re-coded)?

4. For aliases (E_3), the relevant ambiguity is "this alias-string appears on
   N distinct ERP products". How should the band shrink as alias overlap rises?

5. Is there a published unsupervised-band-derivation technique in the entity-
   resolution / probabilistic-record-linkage literature (Fellegi-Sunter, Newcombe)
   that I should be using instead of building this from scratch?

Output format: a principled formula or procedure per stratum, plus a worked
example with realistic ERP-master ambiguity rates (pretend ~1% of current_gtins
collide, ~5% of aliases overlap across products).
```

## Follow-up B — cascade-band consistency under Jaro-Winkler² scaling

```
Context: My cascade has non-overlapping confidence bands by stratum:

  E_1: [0.95, 1.00]   E_2: [0.85, 0.95]   E_3: [0.70, 0.85]   E_4: [0.30, 0.70]

Your prior response recommended w = x^2 (or x^3) where x is the Jaro-Winkler
similarity for E_4. Jaro-Winkler ranges over [0, 1], so x^2 also ranges over
[0, 1] — which conflicts with the [0.30, 0.70] stratum band for E_4. A
high-similarity fuzzy match (say x = 0.95, so x^2 = 0.90) would produce a
confidence above 0.70, invading E_3's stratum and inverting the priority order
(a fuzzy E_4 match scoring higher than an alias E_3 match).

Question: which is the right resolution?

  (a) Rescale: w = 0.30 + 0.40 · x^2, mapping Jaro-Winkler [0, 1] into the
      [0.30, 0.70] stratum band. Cascade priority is preserved by construction,
      but the rescaling itself is ad hoc — why a linear rescaling on top of a
      squared similarity?

  (b) Drop the strict-band model entirely: each stratum produces confidences
      over [0, 1] using its own scoring procedure. The cascade priority controls
      *which generator fires first* (the higher-priority strata still pre-empt
      lower-priority ones; we never call E_4 if E_3 produces a candidate). The
      resulting confidence is reported as-is, even if a fuzzy match scores
      higher than a typical alias match.

  (c) Some third framing I'm missing? E.g., calibrate each stratum independently
      against its own reliability profile, allowing overlap but ensuring the
      *expected* confidence ordering matches stratum order?

For (b), what's the right way to keep the operator's mental model clean? The
review-queue surface needs to display both the stratum (E_4 fuzzy) and the
confidence so operators understand "this match was fuzzy-generated but scored
high".

For (c), is there a published technique for stratum-keyed calibration that
preserves a partial order on expected reliability without requiring strict
band-disjointness?

Output format: a recommendation with reasoning, plus the operational
consequences for the review-queue UX. If (c), reference the technique.
```
