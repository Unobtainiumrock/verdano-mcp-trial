"""End-to-end pipeline: forecast CSV → FulfillmentClassification[].

Per formalism §6.2, the compute pipeline is a DAG of pure functions; the FSM
transitions consume DAG outputs (formalism §6.3). The current trial-scope
exposure is the `analyze_week_fulfillment` entry-point.
"""

from verdano.pipeline.analyze import (
    AnalysisResult,
    ErpSnapshot,
    analyze_week_fulfillment,
    case_pack_convert,
    customer_for_retailer,
)
from verdano.pipeline.drift import analyze_forecast_plausibility

__all__ = [
    "AnalysisResult",
    "ErpSnapshot",
    "analyze_forecast_plausibility",
    "analyze_week_fulfillment",
    "case_pack_convert",
    "customer_for_retailer",
]
