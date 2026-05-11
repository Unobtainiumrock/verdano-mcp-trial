"""`analyze_week_fulfillment` — the DAG entry-point per formalism §6.2.

Compose: Adapter → Resolver → case-pack conversion → Classifier. The output
is a list of `FulfillmentClassification` records ready for operator surface
or MCP wrapping.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

from verdano.adapters import Adapter, get_spec
from verdano.adapters.raw import RawDemandLine
from verdano.allocation import Classifier, FTPCalculator
from verdano.canonical import (
    CanonicalDemandLine,
    FulfillmentClass,
    FulfillmentClassification,
    MappingResult,
    RetailerCode,
)
from verdano.erp.models import (
    Customer,
    InventoryPosition,
    OpenOrder,
    Product,
    Warehouse,
)
from verdano.mapping import MasterIndex, Resolver
from verdano.mapping.priors import DEFAULT_PRIORS, CalibrationPriors
from verdano.mapping.resolver import DEFAULT_HANDLERS, StratumHandler

if TYPE_CHECKING:
    from verdano.llm.client import LLMClient


@dataclass(frozen=True)
class ErpSnapshot:
    """One-shot ERP state used as input to the pipeline.

    Read once at pipeline entry; immutable thereafter so DAG nodes are pure
    functions of their inputs (formalism §6.2 — node-level purity).
    """

    products: list[Product]
    customers: list[Customer]
    warehouses: list[Warehouse]
    inventory: list[InventoryPosition]
    open_orders: list[OpenOrder]


class AnalysisResult(BaseModel):
    """Aggregated output of `analyze_week_fulfillment`.

    Carries the per-line classifications plus a small summary tally for
    quick operator scanning. The MCP wrapper renders this directly as the
    tool's response.
    """

    model_config = ConfigDict(frozen=True)

    retailer: RetailerCode
    iso_week: str
    summary: dict[FulfillmentClass, int] = Field(
        description="Tally of lines per classification."
    )
    classifications: list[FulfillmentClassification]


def customer_for_retailer(
    customers: list[Customer], retailer: RetailerCode
) -> Customer | None:
    """Find the sold-to root customer for a retailer code.

    Heuristic: case-insensitive substring match of the retailer code on the
    sold-to customer name. Trial fixtures use `Tesco UK` / `Sainsbury's UK`.
    """
    needle = retailer.lower().removesuffix("s")
    for c in customers:
        if c.type == "sold_to" and needle in c.name.lower():
            return c
    return None


def case_pack_convert(
    raw: RawDemandLine,
    mapping: MappingResult,
    products_by_sku: dict[str, Product],
) -> CanonicalDemandLine:
    """Finalize a `CanonicalDemandLine` from raw + mapping.

    If the source unit is `units`, divide by `case_pack` (ceiling). The
    ceiling reflects integer-case shipping reality (formalism §4.5) and
    introduces a small over-fulfillment bias that the system tracks.

    If the mapping is unresolved, we still emit a CanonicalDemandLine with
    `quantity_cases = 0` so it can be classified as `Blocked` downstream.
    The conversion intentionally does not raise — separation of concerns.
    """
    inferred = raw.inferred
    if raw.raw_unit_mode == "cases":
        cases = raw.raw_quantity
    elif raw.raw_unit_mode == "units" and mapping.erp_sku is not None:
        product = products_by_sku.get(mapping.erp_sku)
        if product is None:
            logger.warning(
                "mapped sku %s not in products_by_sku; defaulting case_pack=1",
                mapping.erp_sku,
            )
            inferred = True
        case_pack = product.case_pack if product else 1
        cases = math.ceil(raw.raw_quantity / case_pack)
    else:
        cases = 0

    return CanonicalDemandLine(
        retailer=raw.retailer,
        iso_week=raw.iso_week,
        retailer_key=raw.retailer_key,
        location_label=raw.location_label,
        quantity_cases=cases,
        promo_flag=raw.promo_flag,
        notes=raw.notes,
        inferred=inferred,
    )


def analyze_week_fulfillment(
    *,
    forecast_csv: str | Path,
    retailer: RetailerCode,
    iso_week: str,
    erp: ErpSnapshot,
    priors: CalibrationPriors = DEFAULT_PRIORS,
    auto_threshold: float = 0.90,
    tau_safe: float = 0.90,
    tfidf_min_score: float = 0.5,
    tfidf_min_matched_tokens: int = 2,
    fuzzy_jw_min_score: float = 0.30,
    handlers: list[tuple[str, StratumHandler]] | None = None,
    llm_client: LLMClient | None = None,
) -> AnalysisResult:
    """Run the DAG end-to-end for a single (retailer, week) input.

    Stages (per formalism §6.2 topological order):
      1. Adapter: CSV → list[RawDemandLine] (week-level by aggregation if daily)
      2. Resolver: per-line MappingResult (FS cascade)
      3. Conversion: RawDemandLine + MappingResult → CanonicalDemandLine
      4. Classifier: CanonicalDemandLine + MappingResult → FulfillmentClassification

    Filter to `iso_week` after stage 1 so the rest of the pipeline only sees
    in-window rows.
    """
    spec = get_spec(retailer)
    adapter = Adapter(spec)

    raw_lines = adapter.normalize_forecast(forecast_csv)
    raw_lines = [r for r in raw_lines if r.iso_week == iso_week]

    master = MasterIndex(erp.products)

    effective_handlers = list(handlers or DEFAULT_HANDLERS)
    if llm_client is not None:
        from verdano.llm.entity_resolution import make_llm_stratum

        effective_handlers.append(("llm_augmented", make_llm_stratum(llm_client, master)))

    resolver = Resolver(
        master,
        priors=priors,
        auto_threshold=auto_threshold,
        tfidf_min_score=tfidf_min_score,
        tfidf_min_matched_tokens=tfidf_min_matched_tokens,
        fuzzy_jw_min_score=fuzzy_jw_min_score,
        handlers=effective_handlers,
    )
    products_by_sku = {p.sku: p for p in erp.products}

    ftp = FTPCalculator(
        products=erp.products,
        warehouses=erp.warehouses,
        inventory=erp.inventory,
        open_orders=erp.open_orders,
    )
    classifier = Classifier(ftp, tau_safe=tau_safe)

    customer = customer_for_retailer(erp.customers, retailer)
    sold_to = customer.id if customer else None

    classifications: list[FulfillmentClassification] = []
    for raw in raw_lines:
        mapping = resolver.resolve(raw.retailer_key)
        canonical = case_pack_convert(raw, mapping, products_by_sku)
        classifications.append(classifier.classify(canonical, mapping, sold_to))

    counts: Counter[FulfillmentClass] = Counter(c.classification for c in classifications)
    # Ensure all five labels present in the summary for stable consumer parsing.
    summary: dict[FulfillmentClass, int] = {
        cls: counts.get(cls, 0) for cls in _ALL_CLASSES
    }

    return AnalysisResult(
        retailer=retailer,
        iso_week=iso_week,
        summary=summary,
        classifications=classifications,
    )


_ALL_CLASSES: tuple[FulfillmentClass, ...] = (
    "Safe",
    "AtRisk",
    "AtRiskSevere",
    "NeedsVerification",
    "Blocked",
)
