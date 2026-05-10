# Sources of truth — Gemini conversation transcripts

This file is an **append-only transcript** of the Gemini conversations the user is iterating on. Each section is a single chat exchange or topical block. Newer additions append at the bottom; never edit prior content. The file feeds:

- `primitives/ERP/*.md` — ontological treatment of the ERP layer (sections 1–4 below).
- `primitives/CPG/*.md` — ontological treatment of the CPG layer (sections 5–7 below).
- `docs/architecture/formalism.md` — our co-created mathematical model, with explicit pushback on this source where warranted.

---

## Iteration 1 — ERP primitives ontology (`What are the primitives of ERP`)



While ERPs like SAP, Oracle, or NetSuite are incredibly complex, they can be decomposed into the following core primitives:

### 1. Data Primitives (The Information Layer)
At its core, an ERP is a massive, highly structured database. It categorizes information into three fundamental types to maintain data integrity across the enterprise.

* **Master Data:** The core entities of the business. This data changes infrequently and serves as the primary reference point across all modules. Examples include the Chart of Accounts, Employee Profiles, Customer/Vendor Records, and Product/SKU lists.
* **Transactional Data:** The records of daily business events. This data is created constantly and always references Master Data. Examples include Purchase Orders (POs), Sales Invoices, Journal Entries, and Inventory Movements.
* **Metadata (Configuration Data):** The rules and parameters that govern how the ERP operates. Examples include tax rates, organizational hierarchies, currency conversion rules, and depreciation schedules.

### 2. Architectural Primitives (The System Layer)

The technical constraints that separate an ERP from a loose collection of disparate software tools.

* **The Single Shared Database:** The defining primitive of an ERP. Whether on-premise or cloud-based, all functional modules read from and write to the same centralized database schema. This eliminates data silos and reconciliation errors.
* **Role-Based Access Control (RBAC):** Because all company data is centralized, strict authorization primitives are required. RBAC ensures "Segregation of Duties" (SoD)—for example, ensuring that the user primitive who creates a vendor cannot be the same user primitive who authorizes a payment to that vendor.
* **The General Ledger (GL) Engine:** The ultimate destination of almost all ERP activity. Every operational movement (e.g., moving a pallet of goods in a warehouse) is automatically translated by the ERP into a financial debit or credit in the GL.

### 3. Process Primitives (The Workflow Layer)
Instead of looking at isolated departments, ERPs are built around standardized, cross-functional processes that chain transactional data together. 

* **Procure-to-Pay (P2P):** The cycle of buying things. (Purchase Requisition $\rightarrow$ Purchase Order $\rightarrow$ Goods Receipt $\rightarrow$ Invoice Processing $\rightarrow$ Payment).
* **Order-to-Cash (O2C):** The cycle of selling things. (Sales Order $\rightarrow$ Inventory Allocation $\rightarrow$ Shipping $\rightarrow$ Invoicing $\rightarrow$ Payment Collection).
* **Record-to-Report (R2R):** The cycle of accounting. (Logging Transactions $\rightarrow$ Period Close $\rightarrow$ Consolidation $\rightarrow$ Financial Statements).

### 4. Functional Primitives (The Application Modules)
These are the user-facing pillars that interact with the underlying database and workflows. At a minimum, a true ERP requires:

* **Financials / Accounting:** Managing the ledger, accounts payable (AP), accounts receivable (AR), and fixed assets.
* **Human Capital Management (HCM):** Managing the employee lifecycle, payroll, and timesheets.
* **Supply Chain / Materials Management:** Tracking inventory levels, warehouse management, and procurement logic.

---

## Iteration 2 — Mathematical framing of ERP primitives

> *User: Which parts of this system can be closely modeled in a mathematically rigorous manner? Like in terms of linear maps and set theory? I want to model all of them in this manner with robust latex representation*

The most mathematically rigorous components of an ERP system are the General Ledger, the Data Primitives, and the Role-Based Access Control mechanics. These can be formalized using linear algebra, set theory, and relational algebra.

### The General Ledger Engine

Double-entry accounting is a linear system. Every transaction requires equal and opposite debit and credit entries, meaning the financial state of the enterprise is constrained within a specific mathematical space.

Let the total number of accounts in the Chart of Accounts be $n$. The financial state of the enterprise at time $t$ is a column vector $x_t \in \mathbb{R}^n$.

Every functional event (e.g., shipping a product, paying a vendor) is an operational vector $u_t \in \mathbb{R}^m$, where $m$ is the number of distinct operational event types in the ERP.

The ERP configuration rules act as a linear transformation mapping operational events to financial postings. This is defined by a valuation matrix $W \in \mathbb{R}^{n \times m}$.

The state update equation for the General Ledger is:
$$x_{t+1} = x_t + W u_t$$

To satisfy the double-entry accounting constraint, every transaction must balance. The sum of the changes across all accounts for any valid operation must equal zero. Let $\mathbf{1}$ be a column vector of ones in $\mathbb{R}^n$. The matrix $W$ must satisfy the condition:
$$\mathbf{1}^T W = \mathbf{0}^T$$

This ensures that for any operational vector $u_t$, the financial update $W u_t$ is in the null space of $\mathbf{1}^T$.

### Data Primitives

The foundational data layer maps cleanly to set theory and relational algebra.

Let $\mathcal{D} = \{D_1, D_2, \ldots, D_k\}$ be the finite set of universal domains corresponding to Master Data entities (Employees, Vendors, Materials, Cost Centers).

A Master Data table $M_i$ is a relation over a subset of these domains:
$$M_i \subseteq D_{i_1} \times D_{i_2} \times \cdots \times D_{i_p}$$

Transactional Data $T$ is a sequence of tuples that records events over time. Let $\tau$ represent the time domain. A transaction relation is a subset of the Cartesian product of Master Data domains, measurement domains (like $\mathbb{R}$ for currency or physical quantities), and time:
$$T \subseteq M_1 \times M_2 \times \cdots \times \mathbb{R} \times \tau$$

The core architectural constraint of the single shared database is the enforcement of referential integrity via inclusion dependencies. If a transaction $t \in T$ references a specific vendor $v$, that vendor must exist in the Master Data set. Let $\pi_V(T)$ be the relational projection of the transaction set onto the Vendor domain. The ERP rigidly enforces:
$$\pi_V(T) \subseteq M_{\text{vendor}}$$

### Role-Based Access Control

The authorization system is a structural mapping between users and system capabilities, modeled via set theory and partial orders.

Define three fundamental sets:
- $U$: the set of system users.
- $R$: the set of configured roles.
- $P$: the set of system permissions.

The ERP architecture defines relations to manage assignments rather than direct mappings:
- User Assignment relation: $UA \subseteq U \times R$
- Permission Assignment relation: $PA \subseteq R \times P$

The total permission set available to a specific user $u \in U$ is the image of $u$ under the composition of these relations:
$$\mathrm{Auth}(u) = \{ p \in P \mid \exists\, r \in R \text{ such that } (u, r) \in UA \land (r, p) \in PA \}$$

Segregation of Duties (SoD) introduces negative constraints. Let $S \subseteq P \times P$ be a set of mutually exclusive permission pairs (e.g., the permission to create a vendor and the permission to pay a vendor). An ERP is in a mathematically valid security state if and only if for all users $u \in U$:
$$\forall (p_i, p_j) \in S,\ \neg (p_i \in \mathrm{Auth}(u) \land p_j \in \mathrm{Auth}(u))$$

---

## Iteration 3 — Coverage table (which primitives have math, which don't)

> *User: Give me a table showing which of the primitives and their subcomponents are covered by what's laid out above and show which ones don't have mathematical framing still. Explain why those don't have this framing where applicable*

| Primitive Category | Subcomponent | Mathematical Framing Applied | Missing Mathematical Framing |
|---|---|---|---|
| Data | Master Data | Relational Algebra, Set Theory | None |
| Data | Transactional Data | Relational Algebra, Cartesian Products | None |
| Data | Metadata (Configuration) | Partial (Implicit in Valuation Matrix $W$) | Full formalization. Metadata is highly heterogeneous. Some acts as scalars (tax rates), while other metadata defines boolean logic or UI states. It resists a unified algebraic model due to its arbitrary, business-specific nature. |
| Architectural | Single Shared Database | Set Theory (Referential Integrity constraints) | None |
| Architectural | Role-Based Access Control | Set Theory, Relational Composition, Negative Constraints | None |
| Architectural | General Ledger Engine | Linear Algebra (Vector spaces, Null space) | None |
| Process | Procure-to-Pay (P2P) | None | Process primitives describe temporal sequences of states and actions. They are best modeled as finite state machines, directed acyclic graphs (DAGs), or Petri nets. The previous framing focused on structural and financial constraints rather than sequential workflow logic. |
| Process | Order-to-Cash (O2C) | None | Same as P2P. |
| Process | Record-to-Report (R2R) | None | Same as P2P. |
| Functional | Financials / Accounting | None | Functional primitives are arbitrary software boundaries created for human usability and commercial modularity. They group related tasks but do not represent fundamental data structures or logical axioms. They cannot be rigorously modeled because they are organizational constructs, not mathematical entities. |
| Functional | Human Capital Management | None | Same as Financials. |
| Functional | Supply Chain / Materials | None | Same as Financials. |

### Explanations for missing mathematical framing

**Process Primitives (P2P, O2C, R2R).** The previous framework mapped the spatial and structural constraints of an ERP (how data relates to other data and how financial values balance). Process primitives introduce the dimension of time and sequence. A transaction traversing the O2C process is a state transition. Modeling this requires shifting from static algebras to dynamic models like Markov chains for probabilistic workflow transitions, or Petri nets for concurrent process modeling. The current linear and relational models do not capture the required sequence of operations (e.g., a Goods Receipt must mathematically precede an Invoice Verification).

**Functional Primitives (Application Modules).** Modules like HCM or Supply Chain are UI wrappers and access control boundaries grouped by department. They are not structural components of the database or the accounting engine. Attempting to model them mathematically is a category error. They represent the human-computer interface layer, determining which subsets of relations $M_i$ and $T$ a specific user role interacts with, rather than altering the underlying mathematical truth of the ERP.

**Metadata (Configuration Data).** While the valuation matrix $W$ absorbs some metadata (like defining which operational vector $u_t$ maps to which financial accounts), it fails to capture configuration rules that dictate application behavior. For instance, a configuration rule stating "Inventory cannot drop below zero" is an inequality constraint on a specific domain measurement, but a rule stating "Approval requires two signatures if PO > \$10{,}000" is a boolean logic gate embedded in a workflow. This heterogeneity means metadata must be modeled piecewise rather than through a single, elegant mathematical structure.

---

## Iteration 4 — Scope realignment for the Verdano trial

> *User asked Gemini to consider two paths: (1) build out the missing math (Markov / DAG / FSM), or (2) reframe given the Verdano work-trial brief. Also raised: there's an entire additional set of primitives at the CPG layer; and which parts of the existing ERP-internal math are out of scope.*

### Scope realignment: ERP vs. CPG layer

The rigorous mathematical framing of the internal ERP engine (General Ledger null spaces, valuation matrices, and referential database integrity) is **out of scope** for the Verdano work trial.

This challenge treats the ERP as an **external state machine accessed via an API**. You are not building the ERP. You are building an integration and reconciliation layer that sits strictly downstream of the ERP and upstream of the retailer. The focus must shift from internal mathematical consistency to external data normalization and agentic orchestration.

### Workflow math: DAGs vs. FSMs vs. Markov chains

Based on the reconciliation problem presented, here is the breakdown of the mathematical models:

- **Markov Chains (Discard).** Order fulfillment and supply chain reconciliation are not stochastic processes governed by transition probabilities. A SKU moving from "forecasted" to "fulfilled" is deterministic business logic, not a random walk.
- **Finite State Machines (FSMs).** Use FSMs to model the lifecycle of the business entities. An order exists in a discrete state space: $S = \{\text{Draft}, \text{Pending\_Review}, \text{Allocated}, \text{Blocked}\}$. Transitions are triggered by boolean constraints (e.g., $\text{Inventory} \geq \text{Demand}$). This is highly applicable for the optional "Create ERP order drafts" requirement.
- **Directed Acyclic Graphs (DAGs).** Use DAGs for the execution and reconciliation pipeline. The system processes a dependency graph. Node $A$ (Fetch Retailer CSV) and Node $B$ (Fetch ERP Inventory) must resolve before Node $C$ (Normalize Data) executes, which precedes Node $D$ (Calculate Risk). When defining tools for an MCP server, conceptualizing the pipeline as a DAG prevents race conditions and allows the LLM to reason about execution order.

### The CPG primitives

The CPG layer introduces mathematical primitives distinct from the ERP accounting layer. These define the demand planning and supply chain reality.

**1. The Bipartite Mapping Graph (Entity Resolution).** Retailers and the ERP do not share a primary key. Reconciling disparate systems is a bipartite graph matching problem. Let $V_R$ be the set of retailer SKUs and $V_E$ be the set of ERP SKUs. The mapping is a bipartite graph $G = (V_R \cup V_E, E)$ where edges represent valid mappings. Ambiguous mappings are unconnected vertices or edges assigned a confidence weight $w < 1$.

**2. The Spatiotemporal Demand Tensor.** Demand is not a scalar. It is a tensor $D \in \mathbb{R}^{S \times L \times T}$ where $S$ represents SKUs, $L$ represents locations, and $T$ represents time periods. The operational challenge is aligning the Tesco $T$ (which might be a weekly aggregate) with the ERP $T$ (which might be daily).

**3. The Allocation Constraint.** Let the total available ERP supply for a specific SKU be $s$. Let the forecasted demand from $n$ retailers be a vector $d \in \mathbb{R}^n$. The allocated quantity vector $x \in \mathbb{R}^n$ must satisfy the system of inequalities:
$$\sum_{i=1}^{n} x_i \leq s$$
$$0 \leq x_i \leq d_i \quad \forall i \in \{1, \ldots, n\}$$

When $\sum d_i > s$, the system is in an "at-risk" state requiring human review or a secondary priority function.

### MCP server architecture for Verdano

To satisfy the evaluation criteria prioritizing OOP, adapters, and scalability, the MCP server should be structured around a Standard Internal Representation (SIR).

- **The Adapter Pattern.** The system must protect the core logic from spreadsheet chaos. Implement a base `RetailerAdapter` interface with methods like `normalize_forecast()` and `normalize_epos()`. Concrete classes like `TescoAdapter` ingest the specific CSV shape and output standard objects. This satisfies the requirement to scale from 2 to 200 customers.
- **Core Entities.** Define strict base classes for `NormalizedForecast`, `InventorySnapshot`, and `FulfillmentRisk`. The ERP API data and the adapter outputs must be cast into these objects before any comparison logic occurs.
- **Tool Abstraction.** Keep the MCP tools coarse-grained. If you expose granular tools (like `get_tesco_row`), you force the LLM into tight orchestration loops that drain context windows and increase failure rates. Build a tool like `analyze_week_fulfillment(week_start_date)` that executes the internal DAG, resolves the bipartite mapping, and returns a structured JSON summary of safe, at-risk, and blocked lines.
- **Handling Ambiguity.** For the mapping layer, implement a lookup adapter. If a Tesco SKU does not perfectly match an ERP SKU, surface this edge case explicitly in the tool's output payload to trigger the required "human review" state.

> *Gemini closed by asking: "How do you plan to handle the fuzzy matching logic between the messy retailer CSV strings and the clean ERP entity names within your mapping adapter?"* — open question, deferred to the formalism doc and a future iteration.

---

> **Where this source's recommendations diverge from project commitments**, see [`docs/architecture/formalism.md`](../architecture/formalism.md) §"Where this diverges from the Gemini source, and why" for the explicit deltas (Markov-not-fully-discarded for drift; subclass-vs-config adapter shape; bipartite-graph framing extended with stratified evidence; demand tensor recast as change-of-basis between incompatible bases).

---

## Iteration 5 — Confidence calibration (response to Prompt 1 in `prompts-for-gemini.md`)

The challenge of mapping "vibes-based" bands into a mathematically principled space without labeled data requires grounding the confidence weights in the structural properties of the data itself.

### Options for principled calibration

1. **Information-theoretic overlap (TF-IDF).** Treat the ERP master as a corpus. Calculate the Inverse Document Frequency (IDF) of every token. The confidence of an alias match is the sum of the IDFs of the matching tokens divided by the total IDF of the retailer SKU. *Tradeoffs:* zero labeled data, theoretically grounded (matches on rare tokens like "500ml" or "Vegan" mean less than a match on a unique brand sub-name), operationally simple to compute.

2. **String distance with exponential decay.** Use a normalized distance $d(x,y) \in [0,1]$ (e.g., Normalized Levenshtein). Map distance to confidence via $w(d) = e^{-\lambda d}$. Calibrates against the assumption that typographical errors are exponentially less likely as edit distance grows. $\lambda$ acts as a strictness dial.

3. **Bipartite graph connectivity (ambiguity density).** If a retailer SKU $v_r$ fuzzy-matches 5 ERP SKUs, the confidence of any single edge is penalized by vertex degree: $w(e) = \text{base\_score} / \log(1 + \deg(v_r))$. Solves 1-to-many ambiguity from graph topology directly; requires the full $V_R \times V_E$ distance matrix.

### Right shape for fuzzy matches

Normalized Levenshtein yields a linear penalty, which poorly reflects reality (a 2-character difference in a 10-character string is often catastrophic for SKUs, not an 80% match). **Jaro-Winkler** is the canonical choice for short record-linkage (names/SKUs) because it heavily weights *prefix* matches (vital for SKUs where the brand is usually first). Jaro-Winkler distance scaled by exponential decay provides the most defensible unsupervised distribution.

### Path to learned calibration

- **Platt scaling (logistic calibration):** best for small data; fits a sigmoid over base scores. Starts paying off at $N \approx 200$ labeled examples.
- **Isotonic regression:** non-parametric, perfectly monotonic; no shape assumptions. Strictly more data to avoid overfitting; starts paying off at $N \approx 1000$.
- **Beta calibration:** ideal for inputs already bounded in $[0,1]$ (like Jaro-Winkler). Often outperforms Platt for bounded scores.

### Specific recommendations

- **Trial scope (8-hour build, no labels):** Use Jaro-Winkler similarity. If similarity is $x$, set $w = x^2$ or $w = x^3$ to artificially suppress mid-tier "vibes" and create a starker contrast between true matches and noise. Do not build TF-IDF for an 8-hour trial; over-investment.
- **Production scope (post-trial):** Logistic Regression (Platt scaling) taking Jaro-Winkler, Token Overlap, and Vertex Degree as the three features, trained on operator resolutions.

---

## Iteration 6 — Disaggregation kernel (response to Prompt 2)

This is a classic temporal disaggregation problem (Denton or Chow-Lin method in econometrics, applied here to CPG).

### Candidate formulations

1. **Simplex-constrained least squares (NNLS).**
   $$\min_{K} \| K D_{\text{weekly}} - D_{\text{actual}} \|_F^2 \quad\text{s.t.}\quad K \geq 0,\ \mathbf{1}^T K = \mathbf{1}^T$$
   The constraint $\mathbf{1}^T K = \mathbf{1}^T$ ensures column-stochasticity (weights for the days of a given week sum to 1), perfectly satisfying $A K = I_{|T_w|}$.

2. **Regularized matrix factorization.** Add a smoothing penalty $+ \lambda \|L K\|_F^2$ where $L$ is a discrete Laplacian. Prevents overfitting to extreme single-day spikes by forcing adjacent days to have correlated weights.

### Covariates and identifiability

Parameterizing $K(\theta;\,\text{covariates})$ is essentially estimating a multinomial logistic regression for day-of-week shares. With small $N$ the degrees of freedom consume the signal, leading to wild identifiability issues. For CPG, week-of-year seasonality usually affects the *weekly volume* ($D_{\text{weekly}}$), not the *day-of-week distribution* ($K$). Keep $K$ independent of covariates until you have multi-year data.

### Defensible default without EPOS

A uniform kernel $K_{d,w} = 1/7$ is **operationally dangerous** because it triggers false stock-out alerts early in the week and hides them late in the week (grocery sales heavily skew Thursday/Friday/Saturday).

### Specific recommendations

- **Trial scope (1 week EPOS):** Config-declared static profile based on standard UK grocery behavior. E.g., $K = [0.10,\, 0.10,\, 0.10,\, 0.15,\, 0.25,\, 0.20,\, 0.10]^T$ for Mon–Sun. Immediately defensible as "best-practice DOW profile" and infinitely better than uniform.
- **Production scope (6 months EPOS):** Simplex-constrained NNLS. Six months ($\approx 26$ weeks) is enough to learn a highly accurate static $K$ vector per retailer.

---

## Iteration 7 — Allocation objective under supply scarcity (response to Prompt 3)

This is the exact domain of operations research and linear programming for supply-chain management.

### Comparison table of canonical objectives

| Objective | Formulation | Winner profile under stress | Literature / Origin | Suitability for CPG |
|---|---|---|---|---|
| Proportional (Pro-Rata) | $x_i = d_i \cdot \frac{s}{\sum d_j}$ | Completely neutral; pain shared equally as % of ask | Standard OR / contract law | **High** — defensible, commercially safe, widely expected |
| Max-Min Fair | $\max\,(\min_i x_i / d_i)$ | Protects smaller orders; nobody gets 0% until everyone gets $X\%$ | Roughgarden (fair division); network flow | Medium — large retailers can take massive cuts |
| Weighted Priority | $\max \sum \rho_i x_i \text{ s.t. } x \in \Pi$ | High-$\rho_i$ takes all up to $d_i$, starving others | Bertsimas (linear optimization) | Low (unless strict tiering exists) |
| Egalitarian | $\max \sum U(x_i)$, $U$ concave | Tends toward equal absolute units; punishes large accounts | Nash bargaining | Low |

### The unification parameter

The formulation $x_i = (\rho_i \cdot d_i) \cdot s / \sum_j (\rho_j \cdot d_j)$ is an analytical heuristic but is **mathematically unsafe** because it can violate the upper-bound constraint $x_i \leq d_i$ if supply is high and $\rho_i$ is heavily skewed.

Rigorous unification: a **water-filling algorithm**. Allocate supply continuously, proportional to $\rho_i \cdot d_i$, and "freeze" an allocation when it hits $x_i = d_i$, redistributing remaining supply to unfrozen retailers.

### Defensible default for CPG

**Pro-rata.** If no strict commercial priority exists, pro-rata is the only legally and commercially defensible default. Guarantees identical fill rates ($x_i / d_i$) across retailers. Hyperparameter-free, trivially explainable to angry buyers.

### Escalation tripwire policy

The standard OR pattern is **fill-rate thresholding** (service-level agreements):

- **Auto-allocate** if $s / \sum d_i \geq \tau_{\text{safe}}$ (e.g., $0.95$). Financial impact of a 5% cut is easily absorbed by retailer safety stock.
- **Human review (tripwire)** if $s / \sum d_i < \tau_{\text{safe}}$. System flags as `AtRisk_Severe` and halts.
- **Recommendation:** hardcode $\tau_{\text{safe}} = 0.90$ for the work trial. Demonstrates understanding of the boundary between algorithmic automation and commercial risk.

---

## Iteration 8 — Exact-match baseline scores via Fellegi-Sunter (response to follow-up A in `prompts-for-gemini.md`)

The canonical framework for this in the probabilistic record-linkage literature is the **Fellegi-Sunter (1969)** model. It abandons "fixed bands" entirely in favor of computing a log-likelihood ratio for every specific match, driven by two empirical probabilities:

1. **$m$-probability:** $P(\text{attribute agrees} \mid \text{records represent the same entity})$
2. **$u$-probability:** $P(\text{attribute agrees} \mid \text{records represent different entities})$

In an unsupervised, single-source scenario (where you only control the ERP master), you cannot easily estimate the $m$-probability (the retailer's typo/error rate), but you can calculate the $u$-probability with perfect precision. It is exactly the **collision rate** of that specific key in your database.

By applying Bayes' theorem to the Fellegi-Sunter parameters, we can derive a principled, unsupervised confidence score $w(x) \in [0, 1]$ for a match on any specific string $x$.

### The principled derivations

Let $N$ be the total number of active SKUs in the ERP. Let $K_x$ be the number of distinct ERP SKUs that share the matched string $x$ (the ambiguity density). Let $\epsilon$ be a global "data corruption prior" (the baseline probability that a retailer string is fundamentally wrong, despite matching).

The exact-match confidence for a specific string $x$ is the posterior probability that the match is correct:

$$w(x) = \frac{1 - \epsilon}{K_x}$$

This simple formulation replaces static bands with dynamic, data-driven bounds.

#### 1. $E_1$: current GTINs

You do not need a global upper bound. The upper bound is defined dynamically by the uniqueness of the matched GTIN.

- **Procedure:** Calculate $K_x$ for the matched GTIN. If the GTIN is globally unique in the ERP, $K_x = 1$.
- **Formula:** $w_1(x) = \dfrac{1 - \epsilon}{K_x}$
- **Bound logic:** Theoretical upper bound is $1 - \epsilon$. Lower bound is $(1 - \epsilon) / \max(K_{\text{gtin}})$. If a GTIN is overloaded onto 3 products, the confidence of that specific match mathematically collapses to $\approx 0.33$, violently pulling it out of the $E_1$ "vibes" band and correctly flagging it for human review.

#### 2. $E_2$: legacy GTINs and obsolescence

The Fellegi-Sunter logic applies, but legacy identifiers carry structural risk: a legacy GTIN might map to a product formulation that has been superseded, meaning the retailer *thinks* they are ordering the old SKU, but you must fulfill the new one.

- **Procedure:** Introduce an obsolescence penalty $\gamma \in (0, 1)$, representing the historical rate at which legacy GTINs point to inactive/superseded SKUs.
- **Formula:** $w_2(x) = (1 - \gamma) \cdot \dfrac{1 - \epsilon}{K_x}$

#### 3. $E_3$: aliases

Alias overlap is not a bug; it is a feature of human-entered data (e.g., matching on "Verdano Vegan Sausage 500g"). The ambiguity density $K_x$ naturally penalizes generic aliases. However, aliases are also subject to higher $m$-probability failures (inconsistent formatting).

- **Procedure:** Compute the frequency $K_x$ of the alias string in the ERP. Because aliases are informal, a collision on a generic string ("Vegan Patty") provides exponentially less signal than a collision on a highly specific string. Apply a dampening exponent $\alpha > 1$ to the collision count to penalize highly overloaded aliases more aggressively than GTINs.
- **Formula:** $w_3(x) = \dfrac{1 - \epsilon}{K_x^{\alpha}}$

### Worked example: ERP-master calibration

**State of the ERP master:**

- Total SKUs: $N = 200$.
- GTIN collision: $1\%$ of current GTINs appear on 2 distinct SKUs (e.g., shared across a promotional and standard variant). The rest are unique.
- Alias overlap: $5\%$ of aliases are shared. Specifically, the alias "Spicy Chorizo" maps to $K = 3$ different SKUs.
- Priors: $\epsilon = 0.02$ (2% baseline retailer error rate), $\gamma = 0.10$ (10% legacy obsolescence risk), $\alpha = 1.5$ (alias penalty).

**Evaluating matches in production:**

**Scenario A — exact match on $E_1$ (unique GTIN '0501234567890').** $K_x = 1$. $w_1 = (1 - 0.02) / 1 = 0.98$. Cleanly auto-maps.

**Scenario B — exact match on $E_1$ (colliding GTIN '0509999999999').** $K_x = 2$. $w_1 = 0.98 / 2 = 0.49$. Despite being an exact GTIN match, the data-driven confidence plunges to 0.49. The static vibes-band of $[0.95, 1.00]$ would have falsely auto-allocated this to a random variant. It is now correctly surfaced for human review.

**Scenario C — exact match on $E_2$ (legacy GTIN, unique).** $K_x = 1$. $w_2 = (1 - 0.10) \cdot (1 - 0.02) / 1 = 0.88$. Sits safely below current GTINs, representing the slight risk of obsolescence, but likely high enough to auto-map depending on tripwire.

**Scenario D — exact match on $E_3$ (alias 'Spicy Chorizo').** $K_x = 3$. $w_3 = 0.98 / 3^{1.5} = 0.98 / 5.196 = 0.18$. The alias is too generic. The exponent successfully crushes the confidence, demanding operator review.

### Summary for the MCP implementation

Do not code fixed bands `if E_1 return 0.95`.

Instead, inside your `normalize_forecast()` adapter, pre-compute the frequency dictionary $K_x$ for all keys in the ERP master. When a match occurs at any stratum, execute the corresponding formula. This allows the system to behave perfectly probabilistically without requiring a single labeled training example, satisfying the core mathematical requirements of Fellegi-Sunter while fitting within the constraints of an 8-hour work trial.

---

## Iteration 9 — Cascade-band consistency under JW² scaling (response to follow-up B in `prompts-for-gemini.md`)

The mathematically correct resolution is **(b) Drop the strict-band model entirely**, augmented by the principled calibration of **(c)**.

Strict, non-overlapping confidence bands are an artifact of deterministic, rules-based engines. As soon as you shift to a probabilistic scoring mechanism (like the Bayesian collision-rate math we derived for exact matches, or Jaro-Winkler for fuzzy), forcing scores into rigid bands destroys their calibration. A confidence score should represent the true probability of a correct match. Squeezing a 95% reliable fuzzy match into a $[0.30, 0.70]$ band turns a meaningful probability into a meaningless, arbitrary rank.

### 1. The separation of concerns (reasoning for B)

In modern probabilistic record linkage, you must separate **Discovery** from **Scoring**.

- **Discovery (the cascade):** The priority cascade ($E_1 \to E_2 \to E_3 \to E_4$) is a computationally efficient search heuristic — what the literature calls a *blocking strategy*. It determines *in what order* we look for candidates. We search for exact GTINs first because they have the highest *expected* precision. If we find a hit, we stop searching.
- **Scoring (the likelihood):** Once a candidate is generated by any tier, it is evaluated strictly on its own merits.

It is entirely mathematically coherent for a pristine fuzzy match (e.g., Jaro-Winkler $0.98$ on a highly specific string) to be more trustworthy than an exact alias match on a highly overloaded, generic string ("Vegan Patty"). Inverting the priority order in the *score* is not a bug; it is the system correctly recognizing that the heuristic generated a weak candidate, but the fallback generated a strong one.

### 2. The published technique (the "third framing" / C)

What you are describing in (c) is formalized in ML literature as **Cascaded Classification** or, in the specific domain of record linkage, treating the matching rule as a feature in a unified **Logistic Calibration (Platt scaling)** model.

When you transition from the unsupervised work-trial phase to the supervised production phase, you don't calibrate each stratum in isolation. You fit a single logistic regression model where the outputs are the true probabilities:

$$
P(\text{Match} = 1 \mid \text{Score}, \text{Stratum}) = \sigma\!\left( w_0 + w_1 \cdot \text{Score} + \sum_k \beta_k \cdot I_k \right)
$$

where $I_k$ is a one-hot indicator for the stratum that generated the match.

The model will learn negative weights for the lower strata (e.g., $\beta_4 < \beta_1$). This applies a structural penalty to fuzzy matches, enforcing the *expected* reliability ordering (an $E_1$ match will baseline higher than an $E_4$ match), but importantly, it still allows a high-scoring $E_4$ to overlap with a low-scoring $E_3$ if the data justifies it.

### 3. Operational consequences for the review-queue UX

If you abandon strict bands, the operator's mental model must shift from "Score = Quality + Lineage" to explicitly separating the two concepts in the UI.

For the work trial, your MCP tool should output (and the downstream UI should render) two distinct fields for every surfaced match:

1. **Lineage (the "How"):** A categorical label showing which stratum generated the candidate.
   - *UX:* `[Tag: Exact GTIN]` or `[Tag: Fuzzy Alias]`
2. **Confidence (the "How Much"):** The raw, un-banded probabilistic score.
   - *UX:* `Confidence: 92%`

**The tripwire logic.** Because the scores are true probabilities, your auto-allocation tripwire becomes globally unified. You do not need different thresholds for different strata.

- If `Confidence > 0.90`, auto-allocate (regardless of whether it was an $E_1$ or an incredibly clean $E_4$).
- If `Confidence < 0.90`, push to human review.

When an operator looks at the review queue, they will occasionally see an $E_4$ match with a 92% confidence (auto-allocated) and an $E_3$ match with a 65% confidence (flagged for review). Because the UI clearly separates the generator lineage from the data-driven score, the operator understands *why* the system made the decision: "It was a fuzzy match, but the strings were nearly identical, so the system trusted it more than that highly ambiguous exact alias."