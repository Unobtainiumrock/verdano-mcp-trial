"""Canonical entity contracts for the Verdano reconciliation layer.

These are the morphism domains/codomains in the formalism (§2). All
adapter outputs and pipeline-internal state types live here.
"""

from verdano.canonical.models import (
    CanonicalActualsLine,
    CanonicalDemandLine,
    FulfillmentClass,
    FulfillmentClassification,
    MappingEvidence,
    MappingResult,
    MappingState,
    RetailerCode,
    RetailerProductKey,
    Stratum,
    known_retailer_codes,
    register_retailer_code,
    validate_retailer_code,
)

__all__ = [
    "CanonicalActualsLine",
    "CanonicalDemandLine",
    "FulfillmentClass",
    "FulfillmentClassification",
    "MappingEvidence",
    "MappingResult",
    "MappingState",
    "RetailerCode",
    "RetailerProductKey",
    "Stratum",
    "known_retailer_codes",
    "register_retailer_code",
    "validate_retailer_code",
]
