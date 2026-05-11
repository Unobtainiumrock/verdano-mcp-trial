"""Tests for runtime registries (FulfillmentClass, MappingState, Stratum, DriftClass, DriftDirection)."""

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
from verdano.drift.types import known_drift_directions


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
        assert strata[:5] == ["gtin_current", "gtin_legacy", "alias_exact", "tfidf_overlap", "fuzzy_jw"]

    def test_register_after(self) -> None:
        register_stratum("llm_test", after="fuzzy_jw")
        strata = known_strata()
        assert "llm_test" in strata
        jw_idx = strata.index("fuzzy_jw")
        llm_idx = strata.index("llm_test")
        assert llm_idx == jw_idx + 1
        _STRATUM_REGISTRY.remove("llm_test")

    def test_idempotent_registration(self) -> None:
        before = len(known_strata())
        register_stratum("gtin_current")
        assert len(known_strata()) == before

    def test_register_append_default(self) -> None:
        register_stratum("EX_test")
        assert known_strata()[-1] == "EX_test"
        _STRATUM_REGISTRY.remove("EX_test")


class TestDriftClassRegistry:
    def test_builtins_registered(self) -> None:
        expected = {"high", "low", "ok", "skipped_unmapped"}
        assert expected <= _DRIFT_CLASS_REGISTRY

    def test_residual_classes_registered(self) -> None:
        import verdano.drift.strategies  # noqa: F401
        expected = {"over_forecast", "under_forecast", "accurate"}
        assert expected <= _DRIFT_CLASS_REGISTRY

    def test_register_new_class(self) -> None:
        register_drift_class("anomalous")
        assert "anomalous" in _DRIFT_CLASS_REGISTRY
        _DRIFT_CLASS_REGISTRY.discard("anomalous")


class TestDriftDirectionRegistry:
    def test_builtins_registered(self) -> None:
        assert {"high", "low", "ok"} <= known_drift_directions()

    def test_residual_directions_registered(self) -> None:
        import verdano.drift.strategies  # noqa: F401
        expected = {"over_forecast", "under_forecast", "accurate"}
        assert expected <= known_drift_directions()
