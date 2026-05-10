# Allocation — free-to-promise under temperature and warehouse constraints

The allocation primitive answers the operational question: **given resolved retailer demand and ERP supply, what can we fulfill?** This is where the safe / at-risk / needs-review classification is computed.

This primitive is the **allocation constraint** Gemini surfaced in [`raw-truth.md`](../../docs/process/raw-truth.md) iteration 4 §"The CPG Primitives" #3, extended with the temperature-band and warehouse-compatibility structure that the Gemini sketch glossed over.

## Free-to-promise (FTP)

For each (`sku`, `iso_week`) we compute available cases across **temperature-compatible warehouses**, net of already-committed open orders in the same window.

$$
\text{ftp}(\textit{sku}, \textit{window}) = \sum_{w \in \mathcal{W}_{\text{compat}}(\textit{sku})} \bigl(a(\textit{sku}, w) - \alpha(\textit{sku}, w)\bigr) \;-\; \sum_{o \in \mathcal{O}(\textit{retailer}, \textit{sku}, \textit{window})} q(o)
$$

where:

- $\mathcal{W}_{\text{compat}}(\textit{sku})$ — warehouses whose `temperature_band` matches the product's `temperature_band`.
- $a(\textit{sku}, w)$ — `available_cases` from `GET /erp/inventory`.
- $\alpha(\textit{sku}, w)$ — `allocated_cases` from `GET /erp/inventory`.
- $\mathcal{O}(\textit{retailer}, \textit{sku}, \textit{window})$ — open orders for this retailer, this SKU, with `required_date` in the window.
- $q(o)$ — quantity in cases on order line $o$.

See [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §5 for the formal statement.

## Classification

Once FTP is computed, each retailer demand line classifies as:

| Class | Condition | Action |
|---|---|---|
| **Safe** | $\text{ftp}(\textit{sku}, \textit{window}) \geq d_{\text{retailer}}(\textit{sku}, \textit{window})$ | Pass through; eligible for order-draft creation. |
| **At-risk** | $0 \leq \text{ftp}(\textit{sku}, \textit{window}) < d_{\text{retailer}}(\textit{sku}, \textit{window})$ | Surface to operator with the gap; do not auto-draft. |
| **Blocked** | The mapping resolution is unresolved or low-confidence | Route to mapping review queue (see [`entity-resolution.md`](entity-resolution.md)). |

Note: `Blocked` is *upstream* of the FTP calculation — we cannot compute FTP for an unmapped SKU. A clean implementation runs entity resolution first and only invokes the allocation primitive on lines that resolved.

## Allocation policy when supply-constrained (D-010)

When $\sum_{r} d_r > s$, the system must choose how to allocate. This is the canonical OR domain of constrained allocation.

### Default: pro-rata (D-010 part 1)

For an SKU and window with total supply $s$ and per-retailer demand $d_i$:

$$x_i = d_i \cdot \frac{s}{\sum_j d_j}$$

Pro-rata is the locked default because (a) Verdano has no strict commercial-priority story, (b) it guarantees identical fill rates across retailers, (c) hyperparameter-free, (d) trivially explainable to angry buyers ("everyone got the same percentage of their ask"). Standard OR / contract-law pattern.

### Weighted variant: water-filling (D-010 part 2)

If per-retailer priority weights $\rho_i \in \mathbb{R}_{\geq 0}$ are eventually introduced, **do not** use the closed-form heuristic

$$x_i = (\rho_i \cdot d_i) \cdot \frac{s}{\sum_j (\rho_j \cdot d_j)}$$

It can violate the upper-bound constraint $x_i \leq d_i$ when $\rho$ is skewed (Gemini iteration 7 caught this). Use a **water-filling algorithm** instead:

1. Allocate supply continuously, proportional to $\rho_i \cdot d_i$.
2. When any $x_i$ hits its cap $d_i$, freeze it.
3. Redistribute remaining supply to unfrozen retailers per the same proportional rule.

Water-filling preserves all polytope constraints by construction. Pro-rata is the special case $\rho \equiv 1$.

### Auto-vs-review tripwire: fill-rate thresholding (D-010 part 3)

The **fill-rate thresholding** pattern (canonical OR / SLA framework) governs the boundary between auto-allocation and human review:

| Condition | Action |
|---|---|
| $s / \sum_i d_i \geq \tau_{\text{safe}}$ | Auto-allocate per chosen objective |
| $s / \sum_i d_i < \tau_{\text{safe}}$ | Classify as `AtRisk_Severe`; route to human review |

$\tau_{\text{safe}}$ is **config-declared, not hardcoded** (this is the one nuance where we diverged from Gemini's "hardcode 0.90 to demonstrate the pattern" — the math doesn't justify a fixed value). Default $0.90$ for trial scope; per-retailer or global override permitted.

Rationale: a small cut (≤ 5%) is easily absorbed by retailer safety stock and doesn't warrant operator interrupt. A severe shortfall has commercial implications the system shouldn't unilaterally make.

### Rejected alternatives

- **Max-min fair** as default: large retailers take disproportionate cuts under stress; commercially fragile.
- **Egalitarian (equal absolute units)**: punishes large accounts for being large. Same problem.
- **Strict priority**: only appropriate when explicit tiering exists (e.g., "Tesco is strategic, others are wholesale").
- **Closed-form weighted heuristic** (above): unsafe under skew.

## Two warehouse subtleties

**Subtlety 1: temperature-band mismatch is not the same as no compatible warehouse.** A chilled product in a system with no chilled warehouse is unfulfillable. A chilled product in a system with a chilled warehouse but with $a - \alpha = 0$ is at-risk. The first is a structural error; the second is a transient stockout. The classification has to distinguish.

**Subtlety 2: cross-warehouse aggregation.** FTP sums *across* compatible warehouses. The allocation surface to the operator should show the per-warehouse breakdown so they can see e.g. "Daventry has 12 cases, Reading has 0; we need 14; need to consolidate or escalate."

## Idempotency at the order-draft layer

Once a line is classified `Safe`, the optional next step is creating an `OrderDraft` via `POST /erp/order-drafts`. Per the API doc and the fixture confirmation, this is **idempotent** via `external_reference` — re-POSTing with the same external reference returns the existing draft.

We commit to deriving `external_reference` deterministically:

$$
\textit{external\_reference}(r, \textit{sku}, w, \ell) = \mathrm{sha256}\bigl(r \,\|\, \textit{sku} \,\|\, w \,\|\, \ell\bigr)
$$

where $r$ is the retailer code, $\textit{sku}$ is the ERP SKU, $w$ is the ISO week, and $\ell$ is the resolved `ship_to_location_id`. See [`workflow.md`](workflow.md) for the broader idempotency framing.

## Connection to the canonical entity model

Allocation reads from `InventoryPosition`, `OpenSalesOrder` (open-order subtraction), and `RetailerToErpMapping` (to get the resolved ERP `sku`). It writes a `FulfillmentClassification` per (retailer, sku, window) tuple, which maps to the Safe / At-risk / Blocked output of the analysis tool.

## Cross-references

- Formal treatment: [`docs/architecture/formalism.md`](../../docs/architecture/formalism.md) §5.
- Related design gap: free-to-promise math, [`working-doc.md`](../../docs/process/working-doc.md) Design gaps vs README evaluation criteria #4.
- Related fixture gotcha: temperature-band cross-check, [`working-doc.md`](../../docs/process/working-doc.md) Data-driven gotchas #4.
- Decisions: D-002 (storage), D-003 (provisional polymorphism on `FulfillmentClassification`).
