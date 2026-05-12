"""Canonical entity contracts for the CPG reconciliation layer.

These are the morphism domains/codomains in the formalism (§2). All
adapter outputs and pipeline-internal state types live here.
"""

from cpg_reconciler.canonical.models import (
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
    known_fulfillment_classes,
    known_mapping_states,
    known_retailer_codes,
    known_strata,
    register_fulfillment_class,
    register_mapping_state,
    register_retailer_code,
    register_stratum,
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
    "known_fulfillment_classes",
    "known_mapping_states",
    "known_retailer_codes",
    "known_strata",
    "register_fulfillment_class",
    "register_mapping_state",
    "register_retailer_code",
    "register_stratum",
    "validate_retailer_code",
]
