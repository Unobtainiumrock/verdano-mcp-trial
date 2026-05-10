"""Unit tests for the fulfillment Classifier.

Covers all five classification branches: Safe, AtRisk, AtRiskSevere,
NeedsVerification, Blocked.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from verdano.allocation.classify import Classifier
from verdano.allocation.ftp import FTPCalculator
from verdano.canonical import (
    CanonicalDemandLine,
    MappingEvidence,
    MappingResult,
    RetailerProductKey,
)
from verdano.erp.models import InventoryPosition, Product, Warehouse

_NOW = datetime(2026, 5, 10, 0, 0, 0)


def _key(name: str = "Test Product") -> RetailerProductKey:
    return RetailerProductKey(retailer="tesco", name=name)


def _demand(qty: int = 10) -> CanonicalDemandLine:
    return CanonicalDemandLine(
        retailer="tesco", iso_week="2026-W20", retailer_key=_key(),
        location_label="Depot", quantity_cases=qty,
    )


def _resolved(sku: str = "VG-TEST", confidence: float = 0.98) -> MappingResult:
    return MappingResult(
        retailer_key=_key(), erp_sku=sku, confidence=confidence,
        state="Resolved",
        evidence=MappingEvidence(stratum="gtin_current", matched_value="test", collision_count=1),
    )


def _needs_verification(sku: str = "VG-TEST") -> MappingResult:
    return MappingResult(
        retailer_key=_key(), erp_sku=sku, confidence=0.50,
        state="NeedsVerification",
        evidence=MappingEvidence(stratum="tfidf_overlap", matched_value="test", collision_count=2),
    )


def _unmapped() -> MappingResult:
    return MappingResult(
        retailer_key=_key(), erp_sku=None, confidence=0.0,
        state="Unmapped", evidence=None,
    )


def _ftp(avail: int = 100) -> FTPCalculator:
    return FTPCalculator(
        products=[Product(
            sku="VG-TEST", name="Test", category="test",
            temperature_band="chilled", case_pack=6,
            current_gtins=[], legacy_gtins=[], aliases=[], status="active",
        )],
        warehouses=[Warehouse(id="WH-C", name="WH-C", temperature_band="chilled")],
        inventory=[InventoryPosition(
            sku="VG-TEST", warehouse_id="WH-C",
            available_cases=avail, allocated_cases=0, as_of=_NOW,
        )],
        open_orders=[],
    )


def test_safe_when_ftp_exceeds_demand() -> None:
    c = Classifier(_ftp(100), tau_safe=0.90)
    result = c.classify(_demand(10), _resolved(), None)
    assert result.classification == "Safe"


def test_at_risk_when_fill_rate_above_tau() -> None:
    c = Classifier(_ftp(9), tau_safe=0.90)
    result = c.classify(_demand(10), _resolved(), None)
    assert result.classification == "AtRisk"
    assert result.fill_rate is not None
    assert result.fill_rate >= 0.90


def test_at_risk_severe_when_fill_rate_below_tau() -> None:
    c = Classifier(_ftp(5), tau_safe=0.90)
    result = c.classify(_demand(10), _resolved(), None)
    assert result.classification == "AtRiskSevere"
    assert result.fill_rate is not None
    assert result.fill_rate < 0.90


def test_blocked_when_unmapped() -> None:
    c = Classifier(_ftp(100), tau_safe=0.90)
    result = c.classify(_demand(10), _unmapped(), None)
    assert result.classification == "Blocked"
    assert result.ftp_cases is None


def test_needs_verification_when_mapping_unconfirmed() -> None:
    c = Classifier(_ftp(100), tau_safe=0.90)
    result = c.classify(_demand(10), _needs_verification(), None)
    assert result.classification == "NeedsVerification"
    assert result.ftp_cases is None


def test_safe_when_demand_zero() -> None:
    c = Classifier(_ftp(100), tau_safe=0.90)
    result = c.classify(_demand(0), _resolved(), None)
    assert result.classification == "Safe"


# --- threshold boundary tests ---


def test_exact_tau_safe_boundary_is_at_risk() -> None:
    """fill rate = 9/10 = 0.90 exactly — should be AtRisk (>= tau_safe), not AtRiskSevere."""
    c = Classifier(_ftp(9), tau_safe=0.90)
    result = c.classify(_demand(10), _resolved(), None)
    assert result.classification == "AtRisk"
    assert result.fill_rate == pytest.approx(0.9)


def test_just_below_tau_safe_is_at_risk_severe() -> None:
    """fill rate = 89/100 = 0.89 — strictly below tau_safe, AtRiskSevere."""
    c = Classifier(_ftp(89), tau_safe=0.90)
    result = c.classify(_demand(100), _resolved(), None)
    assert result.classification == "AtRiskSevere"
    assert result.fill_rate == pytest.approx(0.89)


def _ftp_frozen(avail: int = 100) -> FTPCalculator:
    """FTPCalculator with frozen temperature band warehouse."""
    return FTPCalculator(
        products=[Product(
            sku="VG-FROZEN", name="Frozen Peas", category="frozen veg",
            temperature_band="frozen", case_pack=6,
            current_gtins=[], legacy_gtins=[], aliases=[], status="active",
        )],
        warehouses=[Warehouse(id="WH-F", name="WH-F", temperature_band="frozen")],
        inventory=[InventoryPosition(
            sku="VG-FROZEN", warehouse_id="WH-F",
            available_cases=avail, allocated_cases=0, as_of=_NOW,
        )],
        open_orders=[],
    )


def _resolved_frozen() -> MappingResult:
    return MappingResult(
        retailer_key=_key(), erp_sku="VG-FROZEN", confidence=0.98,
        state="Resolved",
        evidence=MappingEvidence(stratum="gtin_current", matched_value="test", collision_count=1),
    )


def test_safe_with_frozen_temperature_band() -> None:
    """Frozen band should classify identically to chilled; no band-specific logic in Classifier."""
    c = Classifier(_ftp_frozen(100), tau_safe=0.90)
    result = c.classify(_demand(10), _resolved_frozen(), None)
    assert result.classification == "Safe"
    assert result.erp_sku == "VG-FROZEN"


def test_at_risk_severe_with_frozen_band() -> None:
    c = Classifier(_ftp_frozen(5), tau_safe=0.90)
    result = c.classify(_demand(10), _resolved_frozen(), None)
    assert result.classification == "AtRiskSevere"
