# Verdano Foods MCP Work Trial — submission

> **Reviewer entry point: [`docs/usage.md`](docs/usage.md)** — install, run tests, exercise the analysis snippet, configure the MCP server.
>
> The original trial brief is preserved verbatim below. The submission deliverable is the rest of this repository.
>
> **Quick orientation for a 5-minute scan:**
>
> | Want to see... | Look at |
> |---|---|
> | What it does end-to-end | [`docs/usage.md`](docs/usage.md) — paste-and-run snippet |
> | Architecture decisions + alternatives | [`DECISIONS.md`](DECISIONS.md) — 14 chronological D-entries with rationale and pushback |
> | The math (LaTeX-rendered) | [`docs/architecture/formalism.md`](docs/architecture/formalism.md) — Fellegi-Sunter, change-of-basis, water-filling, FSM/DAG |
> | Empirical evidence the system works against the live ERP | [`docs/live-run-results.md`](docs/live-run-results.md) — 7 real drafts created, idempotency confirmed |
> | The four MCP tools | `analyze_week_fulfillment_tool`, `list_review_queue_tool`, `create_drafts_for_safe_lines_tool`, `compare_actuals_vs_forecast_tool` (in [`src/verdano/mcp_server/server.py`](src/verdano/mcp_server/server.py)) |
> | Tests (70 passing, fully offline) | `uv run pytest` |
> | Conceptual ontology (CPG primitives) | [`primitives/CPG/`](primitives/CPG/) |
> | The Gemini conversation transcripts I iterated against | [`raw_truth.md`](raw_truth.md) (process artifact, not deliverable) |
>
> Provenance note: `raw_truth.md`, `prompts.md`, `prompts-for-gemini.md`, and `working-doc.md` are *process artifacts* showing how the design evolved. They're preserved for transparency on the "Articulation & tradeoffs" eval criterion. Skip them if you only want the deliverable.

---

# Verdano Foods MCP Work Trial

Verdano Foods is a UK plant-based CPG brand selling through Tesco and Sainsbury's. Every Monday, the ops team compares retailer forecasts, recent EPOS sales, ERP inventory, and open orders to answer a simple question:

***What can we fulfill next week, what is at risk, and what needs human review?***

Today that work is spreadsheet-driven. Tesco and Sainsbury's represent the same products, dates, locations, and quantities differently. The ERP has products, customers, stock, and orders, but it does not understand retailer-specific spreadsheet shapes or forecast quality.

### Task

Your task is to build an MCP server that gives general purpose AI tools like Claude/ChatGPT useful tools for this workflow.

At a minimum, the AI system should be able to use your MCP server to:

- Compare next week's retailer forecast demand against ERP inventory and open orders
- Identify SKU/retailer lines that are safe, at risk, or blocked by ambiguous mappings

Optional but for additional inspiration:

- Create ERP order drafts for clean lines
- Compare recent EPOS actuals against retailer forecasts to flag likely forecast drift
- Expose mapping confidence and human-review exceptions
- Explain assumptions and source provenance

You will receive:

- Mock retailer forecast and EPOS CSVs
- Access to a small mock ERP API
  - Base url: https://erp.corvera.ai
  - API key: `trial_IxUCtnJZKv6XyF8g-OMSXpQG9Iwe32p7`

You have full flexibility in choosing the tool design and the implementation approach. That said, we care about the following:

- Reasoning behind your choice of level of abstraction and shape of tools
- Use of OOP principles, including polymorphism, to define core entities and interfaces
- Use of adapters to convert messy source data to core business entities

### Evaluation

You will be evaluated on the following:

- Code quality – types, naming, error handling, extensibility (does your solution have a form factor that scales easily from 2 customers to 200 customers?)
- Abstraction quality – tool shapes, decomposition, reusability
- Articulation & tradeoffs – log of decisions and judgements made, along with presentation

### Submission

We anticipate this work trial to take ~8 hours of work, for which you will be compensated for pro-rata. We encourage you to balance the tension of shipping fast and setting a rigorous scalable foundation.

Complete your submission here: https://forms.gle/U5YhJuY7MaubdFTY9
