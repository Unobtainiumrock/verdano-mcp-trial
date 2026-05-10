---
name: Verdano problem ER model
overview: "A first-pass conceptual entity-relationship view of the Verdano Foods work-trial problem: ERP canonical master data, retailer forecast/EPOS facts in incompatible shapes, mappings with confidence, and the supply/demand objects needed to answer safe vs at-risk vs needs-review."
todos: []
isProject: false
---

# Verdano Foods problem space — entity model (first pass)

This is derived from [README.md](../../README.md), [ERP API.md](../../ERP API.md), and the four mock CSVs (Tesco/Sainsbury forecast week 20, EPOS week 19).

## Core tension (what the diagram encodes)

- **Canonical truth** lives in the ERP: products (by internal `sku`), customers (`sold_to` / `bill_to` / `ship_to`), warehouses, inventory (cases by `sku` + `warehouse_id`), committed open orders, and optional order drafts.
- **Retailer reality** arrives as **different shapes**: Tesco uses `tesco_item` + `depot` + **cases** + **calendar delivery dates**; Sainsbury's uses `gtin` (sometimes blank) + `item_name` + **ISO receipt week** + **consumer units** + `temperature_band` + aggregated `geography` ("All Depots").
- **The missing subsystem** (your MCP/tools sit here): **adapters** normalize rows into shared concepts; **mappings** link retailer identifiers to ERP `sku` with **confidence** and **human-review** when ambiguous (README explicitly calls out ambiguous mappings and provenance).

## Entity-relationship diagram (conceptual)

Mermaid `erDiagram` uses conceptual names; attribute lists mix ERP field names and retailer column names where they matter for integration.

```mermaid
erDiagram
  Retailer ||--o{ RetailerProductKey : identifies
  Retailer ||--o{ ForecastDemandLine : publishes
  Retailer ||--o{ EPOSActualLine : publishes

  ERPProduct ||--o{ ProductGtin : has
  ERPProduct ||--o{ ProductAlias : has
  ERPProduct ||--o{ InventoryPosition : stocked_as
  Warehouse ||--o{ InventoryPosition : holds

  ERPSoldToCustomer ||--o{ CustomerHierarchy : sold_to_root
  ERPBillToCustomer ||--o{ CustomerHierarchy : bill_to_of
  ERPShipToLocation ||--o{ CustomerHierarchy : ship_to_of

  ERPSoldToCustomer ||--o{ OpenSalesOrder : places
  OpenSalesOrder ||--o{ OpenOrderLine : contains
  OpenOrderLine }o--|| ERPProduct : references

  ERPSoldToCustomer ||--o{ OrderDraft : may_create
  OrderDraft ||--o{ DraftOrderLine : contains
  DraftOrderLine }o--|| ERPProduct : references
  ERPShipToLocation ||--o{ OrderDraft : ships_to

  RetailerProductKey ||--o{ RetailerToErpMapping : maps_via
  ERPProduct ||--o{ RetailerToErpMapping : maps_to
  RetailerToErpMapping ||--o{ MappingEvidence : supported_by

  ForecastDemandLine }o--o| RetailerProductKey : keyed_by
  EPOSActualLine }o--o| RetailerProductKey : keyed_by

  RetailerLocationGrain }o--|| Retailer : scoped_to
  ForecastDemandLine }o--|| RetailerLocationGrain : at_location_grain
  EPOSActualLine }o--o| StoreOrChannelGrain : segmented_by

  TimeGrain }o--|| Retailer : calendar_convention
  ForecastDemandLine }o--|| TimeGrain : for_period
  EPOSActualLine }o--|| TimeGrain : for_period

  ERPProduct {
    string sku PK
    string name
    int case_pack
    string temperature_band
  }

  ProductGtin {
    string gtin PK
    string kind
  }

  Retailer {
    string code PK
  }

  RetailerProductKey {
    string retailer_code FK
    string tesco_item
    string gtin
    string free_text_name
  }

  RetailerToErpMapping {
    string id PK
    string retailer_code FK
    string erp_sku FK
    float confidence
    string status
  }

  ForecastDemandLine {
    string source_system
    date delivery_date
    string iso_week
    string location_label
    int quantity_cases
    int quantity_units
    bool promo_flag
    string notes
  }

  EPOSActualLine {
    string source_system
    date week_ending
    string iso_week
    string segment_label
    int units_sold
    decimal sales_value
  }

  InventoryPosition {
    string sku FK
    string warehouse_id FK
    int available_cases
    int allocated_cases
  }

  OpenSalesOrder {
    string order_id PK
    string sold_to_customer_id FK
  }

  OpenOrderLine {
    string sku FK
    int quantity_cases
  }

  OrderDraft {
    string external_reference PK
    string sold_to_customer_id FK
    string ship_to_location_id FK
    date required_date
  }

  DraftOrderLine {
    string sku FK
    int quantity_cases
  }
```

**Grokking notes embedded in the diagram**

- **`RetailerProductKey`** is a deliberate composite abstraction: for Tesco the natural key skews toward `tesco_item`; for Sainsbury's it skews toward `gtin` + `item_name` with **nullable GTIN** in the mock data (ambiguous identity).
- **`TimeGrain`** is not one table in any source — Tesco forecasts use **delivery dates**; Sainsbury's uses **ISO weeks** (`receipt_week`); EPOS files use **week ending** (Tesco) vs **week** (Sainsbury's). Any “compare next week” logic spans this boundary.
- **`RetailerLocationGrain`**: Tesco `depot` (e.g. Daventry Chilled) vs Sainsbury's `geography` ("All Depots") vs ERP `ship_to` / `warehouse_id` — fulfillment and temperature rules ([order-drafts validation in ERP API](../../ERP API.md)) tie **ship-to** and **warehouse temperature** to **product temperature_band**.
- **Units**: Tesco forecast is **cases**; Sainsbury's forecast is **units**; Tesco EPOS is **eaches**; Sainsbury's EPOS is **units** — normalization to a single demand/supply unit (typically ERP **cases** via `case_pack`) is a cross-cutting derivation, not a raw column.

## Problem-space map: sources → normalized facts → decisions

```mermaid
flowchart LR
  subgraph sources [External sources]
    TescoFcst[Tesco forecast CSV]
    SainsFcst[Sainsbury forecast CSV]
    TescoEpos[Tesco EPOS CSV]
    SainsEpos[Sainsbury EPOS CSV]
    ErpApi[Mock ERP API]
  end

  subgraph adapters [Adapter layer]
    AT[Adapter_Tesco]
    AS[Adapter_Sainsbury]
    AE[Adapter_ERP]
  end

  subgraph core [Normalized core concepts]
    NKey[RetailerProductKey]
    NFcst[CanonicalDemandLine]
    NEpos[CanonicalActualsLine]
    NInv[InventoryPosition]
    NOpen[OpenOrderExposure]
  end

  subgraph mapping [Mapping and confidence]
    Map[RetailerToErpMapping]
    Conf[Confidence and review queue]
  end

  subgraph decisions [Weekly ops question]
    Safe[Safe to fulfill]
    Risk[At risk]
    Review[Needs human review]
  end

  TescoFcst --> AT
  SainsFcst --> AS
  TescoEpos --> AT
  SainsEpos --> AS
  ErpApi --> AE

  AT --> NKey
  AS --> NKey
  AT --> NFcst
  AS --> NFcst
  AT --> NEpos
  AS --> NEpos
  AE --> NInv
  AE --> NOpen

  NKey --> Map
  Map --> Conf

  NFcst --> Safe
  NFcst --> Risk
  NInv --> Safe
  NInv --> Risk
  NOpen --> Safe
  NOpen --> Risk
  Conf --> Review
  Map --> Review
```

## Lightweight “compare next week” join path (mental model)

```mermaid
flowchart TB
  F[Forecast for target horizon]
  M{Mapped to erp_sku with sufficient confidence}
  I[Sum inventory available_cases by compatible warehouse or ship-to context]
  O[Subtract open order allocations for same retailer or sku]
  D[Optional drift EPOS vs prior forecast shape]

  F --> M
  M -->|yes| I
  I --> O
  O --> SafeRisk[Classify safe vs at risk]
  M -->|no or low confidence| Review[Human review queue]
  NEpos[EPOS actuals prior week] -.-> D
  F -.-> D
```

## Entities you may want as interfaces (README evaluation criteria)

Polymorphism lines up naturally on **`RetailerAdapter` → `NormalizedRow`**, **`RetailerProductKey` refinements** (Tesco key vs Sainsbury key), and **`DemandQuantity`** (cases vs units with `case_pack` resolution from [`GET /erp/products`](../../ERP API.md)).

---

No code changes are required for this deliverable; this file is a reference model for implementing the MCP server and documenting tradeoffs.
