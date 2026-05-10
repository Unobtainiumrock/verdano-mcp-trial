"""Tests for runtime registries (FulfillmentClass, MappingState, Stratum, DriftClass)."""

from __future__ import annotations

import pytest

from verdano.canonical.models import (
    _FULFILLMENT_CLASS_REGISTRY,
    _MAPPING_STATE_REGISTRY,
    _STRATUM_REGISTRY,
    known_fulfillment_classes,
    known_mapping_states,
    known_strata,
    register_fulfillment_class,
    register_mapping_state,
    register_stratum,
)
from verdano.drift.baseline import _DRIFT_CLASS_REGISTRY, register_drift_class


class TestFulfillmentClassRegistry:
    def test_builtins_registered(self) -> None:
        expected = {"Safe", "AtRisk", "AtRiskSevere", "NeedsVerification", "Blocked"}
        assert expected <= known_fulfillment_classes()

    def test_register_new_class(self) -> None:
        register_fulfillment_class("CustomTier")
        assert "CustomTier" in known_fulfillment_classes()
        _FULFILLMENT_CLASS_REGISTRY.discard("CustomTier")

    def test_idempotent_registration(self) -> None:
        before = len(known_fulfillment_classes())
        register_fulfillment_class("Safe")
        assert len(known_fulfillment_classes()) == before


class TestMappingStateRegistry:
    def test_builtins_registered(self) -> None:
        expected = {"Resolved", "NeedsVerification", "Unmapped"}
        assert expected <= known_mapping_states()

    def test_register_new_state(self) -> None:
        register_mapping_state("PendingReview")
        assert "PendingReview" in known_mapping_states()
        _MAPPING_STATE_REGISTRY.discard("PendingReview")


class TestStratumRegistry:
    def test_builtins_in_order(self) -> None:
        strata = known_strata()
        assert strata[:5] == ["E1", "E2", "E3", "E3b", "E4"]

    def test_register_after(self) -> None:
        register_stratum("E5_test", after="E4")
        strata = known_strata()
        assert "E5_test" in strata
        e4_idx = strata.index("E4")
        e5_idx = strata.index("E5_test")
        assert e5_idx == e4_idx + 1
        _STRATUM_REGISTRY.remove("E5_test")

    def test_idempotent_registration(self) -> None:
        before = len(known_strata())
        register_stratum("E1")
        assert len(known_strata()) == before

    def test_register_append_default(self) -> None:
        register_stratum("EX_test")
        assert known_strata()[-1] == "EX_test"
        _STRATUM_REGISTRY.remove("EX_test")


class TestDriftClassRegistry:
    def test_builtins_registered(self) -> None:
        expected = {"high", "low", "ok", "skipped_unmapped"}
        assert expected <= _DRIFT_CLASS_REGISTRY

    def test_register_new_class(self) -> None:
        register_drift_class("anomalous")
        assert "anomalous" in _DRIFT_CLASS_REGISTRY
        _DRIFT_CLASS_REGISTRY.discard("anomalous")
