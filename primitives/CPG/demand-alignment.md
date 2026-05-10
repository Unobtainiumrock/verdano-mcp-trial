# Demand Alignment — change-of-basis between incompatible spaces

Tesco and Sainsbury's both publish "demand for next week" but they publish into **incompatible bases**. Aligning these isn't a matter of reshaping a single tensor — it's a sequence of **change-of-basis** operations between different representations of the same underlying demand.

This is the most substantive **disagreement with the Gemini source**. Gemini framed demand as a single tensor $D \in \mathbb{R}^{S \times L \times T}$ and implied alignment is just choosing axes consistently. The reality is that **each retailer publishes into its own basis**, and the alignment maps between those bases are **asymmetric in information content**.

## The three axes that need alignment

| Axis | Tesco's basis | Sainsbury's basis | Canonical (ERP-side) basis |
|---|---|---|---|
| **Time** | Daily `delivery_date` (Mon–Sat) | ISO weekly `receipt_week` | Daily, `required_date` |
| **Location** | Depot string ("Daventry Chilled") | "All Depots" (aggregate) | `ship_to_location_id` |
| **Unit** | `forecast_cases` | `forecast_units` (consumer units) | Cases (via `case_pack`) |

Every retailer adapter must perform three changes-of-basis on every forecast row.

## Aggregation is total-preserving and lossless; disaggregation is policy-driven and lossy

This asymmetry is the load-bearing fact.

**Aggregation (Tesco daily → ISO-week):** Linear, total-preserving. If $d \in \mathbb{R}^{T_{\text{daily}}}$ is the daily forecast vector and $A \in \{0, 1\}^{T_{\text{weekly}} \times T_{\text{daily}}}$ is an indicator matrix mapping each day to its containing week, then weekly demand is just $A d$. No information loss, no ambiguity. The map has a well-defined left inverse only modulo the choice of *how to redistribute* a weekly total back into days.

**Disaggregation (Sainsbury's "All Depots" → per-depot, or weekly → daily):** Inherently lossy. Sainsbury's gives us a single number per (SKU, week). To produce per-depot demand or per-day demand we must apply a **policy matrix** — proportional split based on historical EPOS-by-region, or hand-declared profile, or assign-to-primary. Every disaggregation requires committing to a policy; every disaggregated value is **derived, not observed**.

See [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §4 for the formal LaTeX treatment.

### Default kernel for trial scope (D-009)

Per **D-009**, the default day-of-week disaggregation kernel for any retailer with no historical EPOS is a **config-declared static profile**:

$$K_{\text{default}} = [0.10,\ 0.10,\ 0.10,\ 0.15,\ 0.25,\ 0.20,\ 0.10]^T \quad (\text{Mon} \to \text{Sun})$$

This is "best-practice UK grocery DOW profile" (grocery sales heavily skew to Thursday/Friday/Saturday). Per-retailer override allowed in the adapter spec.

**Important: uniform $K = 1/7$ is operationally dangerous** (Gemini iteration 6, locked). It triggers false stockout alerts early in the week and hides them late in the week. Never use as default; only acceptable as a deliberate "we explicitly know nothing about the retailer's intra-week pattern" signal — and even then the static UK profile is preferable.

### Production upgrade path (post-trial, ≥ ~26 weeks of EPOS)

Learn $K$ from labeled per-day actuals via **simplex-constrained NNLS with optional Laplacian smoothing**:

$$\min_K \|K D_{\text{weekly}} - D_{\text{actual}}\|_F^2 + \lambda \|L K\|_F^2 \quad\text{s.t.}\quad K \geq 0,\ \mathbf{1}^T K = \mathbf{1}^T$$

where $L$ is a discrete Laplacian penalizing erratic day-to-day weights. The constraint $\mathbf{1}^T K = \mathbf{1}^T$ ensures column-stochasticity ($A K = I_{|T_w|}$ exactly). Per-retailer kernel; ~26 weeks of data is enough to learn a stable $K$ vector.

**Don't parameterize on covariates** at small $N$ — week-of-year seasonality affects weekly *volume*, not the day-of-week *distribution*, and identifiability collapses with small samples.

## Operational consequence: the system declares its operating grain

Because disaggregation is lossy, the system must be explicit about the grain at which any claim is made:

- "Compare next week" is a **week-level** claim. Both retailers can be aligned to ISO-week without information loss (Tesco rolls up; Sainsbury's stays as-is).
- Any **daily** or **per-depot** claim derived from Sainsbury's data must carry an `inferred=true` flag and a reference to the policy that produced it. The operator should be able to inspect "where did this number come from?" and see "Sainsbury's said 180 units across all depots; we split proportionally to your most-recent 4-week EPOS by depot."

This is a primitive of the system: every value carries its provenance.

## Unit conversion is mediated by `case_pack`

Sainsbury's publishes `forecast_units` (consumer units, e.g., 180 individual 400g pots of dahl). The ERP allocates in cases. Conversion uses the ERP product master's `case_pack`:

$$
\text{cases} = \left\lceil \frac{\text{units}}{\text{case\_pack}} \right\rceil
$$

The ceiling reflects the operational reality that you can't ship a fractional case. This introduces a small but real over-fulfillment bias that the system should track (an order draft for a 6-pack `case_pack` against 7 forecasted units commits 12 units of inventory, not 7).

## Size-unit canonicalization is a *separate* pass

Don't conflate "case_pack conversion" with "size-unit conversion". The fixture `Tom Basil Soup 0.5kg` (Sainsbury's) ↔ `Tomato Soup 500g` (Tesco) involves:

1. Name canonicalization: "Tom" → "Tomato" (alias expansion).
2. Size unit conversion: `0.5kg` → `500g` (numerical rescaling).
3. `case_pack` conversion: units → cases (the formula above).

These are three distinct passes, in this order. Conflating them produces silently-wrong reconciliations.

## Connection to the canonical entity model

Demand alignment populates `CanonicalDemandLine` from raw `ForecastDemandLine` rows. The `iso_week` field is *always* present; `delivery_date` is present only for Tesco; `location_label` carries the original retailer string (`"Daventry Chilled"` or `"All Depots"`); `quantity_cases` is the canonicalized output. See [`docs/architecture/verdano-problem-entity-model.md`](../../docs/architecture/verdano-problem-entity-model.md).

## Cross-references

- Formal treatment: [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §4.
- Related fixture gotcha: unit/size aliasing (Tom Basil 0.5kg ↔ Tomato 500g), [`working-doc.md`](../../docs/process/working-doc.md) Data-driven gotchas #3.
- Related fixture gotcha: time-grain alignment, [`working-doc.md`](../../docs/process/working-doc.md) Design gaps vs README evaluation criteria #6.
- Decisions: D-001 (config-driven, so disaggregation policy lives in the retailer spec).
