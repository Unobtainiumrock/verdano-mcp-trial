"""Markov drift strategy tests (D-024).

Covers:
- TransitionMatrix math: from_history, incremental updates, Laplace smoothing,
  stationary distribution, persistence probability
- MarkovDriftContext subclass construction and Liskov compatibility
- markov_strategy with synthetic 4/8/12/52-week histories
- Insufficient-data skip behavior
- Config parsing for Markov settings
- Repository residual history round-trip
- Pipeline wiring (residual -> history accumulation -> markov analysis)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from verdano.adapters.raw import RawActualsLine, RawDemandLine
from verdano.canonical import MappingEvidence, MappingResult, RetailerProductKey
from verdano.config import Settings
from verdano.drift import DriftAnalyzer, DriftContext, DriftReport
from verdano.drift.markov import (
    MARKOV_STATES,
    MarkovDriftContext,
    TransitionMatrix,
    markov_strategy,
    _consecutive_tail_count,
    _kl_divergence,
)
from verdano.erp.models import Product
from verdano.storage import InMemoryRepository, ResidualRecord


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _product(sku: str = "VG-TEST-001") -> Product:
    return Product(
        sku=sku,
        name="Test Product",
        category="meals",
        case_pack=1,
        temperature_band="ambient",
        current_gtins=["5000000000001"],
        legacy_gtins=[],
        aliases=[],
        status="active",
    )


def _retailer_key(name: str = "Test Product") -> RetailerProductKey:
    return RetailerProductKey(retailer="tesco", name=name)


def _mapping(
    name: str = "Test Product", sku: str = "VG-TEST-001"
) -> MappingResult:
    rk = _retailer_key(name)
    return MappingResult(
        retailer_key=rk,
        erp_sku=sku,
        confidence=0.95,
        state="Resolved",
        evidence=MappingEvidence(stratum="gtin_exact", matched_value="5000000000001", collision_count=1),
    )


def _record(
    sku: str = "VG-TEST-001",
    week: str = "2026-W10",
    direction: str = "accurate",
    pct_error: float = 0.0,
) -> ResidualRecord:
    return ResidualRecord(
        erp_sku=sku,
        iso_week=week,
        direction=direction,
        pct_error=pct_error,
    )


def _records_sequence(
    sku: str, directions: list[str], start_week: int = 10
) -> list[ResidualRecord]:
    """Build a sequence of ResidualRecords for a SKU."""
    return [
        _record(sku=sku, week=f"2026-W{start_week + i:02d}", direction=d)
        for i, d in enumerate(directions)
    ]


def _demand_line(
    name: str = "Test Product",
    qty: int = 100,
    promo: bool = False,
) -> RawDemandLine:
    return RawDemandLine(
        retailer="tesco",
        iso_week="2026-W20",
        retailer_key=_retailer_key(name),
        raw_quantity=qty,
        raw_unit_mode="eaches",
        location_label="Tesco Daventry",
        promo_flag=promo,
    )


def _actuals_line(
    name: str = "Test Product",
    units: int = 95,
) -> RawActualsLine:
    return RawActualsLine(
        retailer="tesco",
        iso_week="2026-W19",
        retailer_key=_retailer_key(name),
        segment_label="Tesco Daventry",
        units_sold=units,
        sales_value_gbp=0,
    )


def _build_markov_ctx(
    history: dict[str, list[ResidualRecord]],
    min_weeks: int = 4,
    persistence_threshold: int = 3,
) -> MarkovDriftContext:
    """Build a MarkovDriftContext with a single mapped forecast line."""
    fc = _demand_line()
    ac = _actuals_line()
    mapping = _mapping()
    key_json = fc.retailer_key.model_dump_json()
    products = {"VG-TEST-001": _product()}

    return MarkovDriftContext(
        forecast_lines=[fc],
        actuals_lines=[ac],
        mappings_by_key={key_json: mapping},
        products_by_sku=products,
        iso_week_forecast="2026-W20",
        iso_week_actuals="2026-W19",
        threshold_low=0.5,
        threshold_high=1.5,
        residual_threshold=0.10,
        residual_history=history,
        min_weeks=min_weeks,
        persistence_threshold=persistence_threshold,
    )


# ===================================================================
# TransitionMatrix tests
# ===================================================================


class TestTransitionMatrix:
    def test_empty_matrix_uniform_with_smoothing(self) -> None:
        mat = TransitionMatrix()
        for s1 in MARKOV_STATES:
            for s2 in MARKOV_STATES:
                assert mat.probability(s1, s2) == pytest.approx(1.0 / 3, abs=1e-9)

    def test_update_transition_changes_probabilities(self) -> None:
        mat = TransitionMatrix()
        mat.update_transition("accurate", "accurate")
        mat.update_transition("accurate", "accurate")
        p_aa = mat.probability("accurate", "accurate")
        p_ao = mat.probability("accurate", "over_forecast")
        assert p_aa > p_ao

    def test_row_sums_to_one(self) -> None:
        mat = TransitionMatrix()
        mat.update_transition("accurate", "accurate")
        mat.update_transition("accurate", "over_forecast")
        mat.update_transition("over_forecast", "under_forecast")
        for state in MARKOV_STATES:
            row_sum = sum(mat.probability(state, s) for s in MARKOV_STATES)
            assert row_sum == pytest.approx(1.0, abs=1e-9)

    def test_laplace_smoothing_with_custom_value(self) -> None:
        mat = TransitionMatrix(smoothing=0.5)
        mat.update_transition("accurate", "accurate")
        p_aa = mat.probability("accurate", "accurate")
        p_ao = mat.probability("accurate", "over_forecast")
        assert p_aa == pytest.approx((1 + 0.5) / (1 + 0.5 * 3), abs=1e-9)
        assert p_ao == pytest.approx(0.5 / (1 + 0.5 * 3), abs=1e-9)

    def test_from_history_builds_correct_counts(self) -> None:
        records = _records_sequence("S1", [
            "accurate", "accurate", "over_forecast", "accurate",
        ])
        mat = TransitionMatrix.from_history(records)
        assert mat.total_transitions == 3
        assert mat.probability("accurate", "accurate") > mat.probability("accurate", "under_forecast")

    def test_from_history_single_record_no_transitions(self) -> None:
        records = _records_sequence("S1", ["accurate"])
        mat = TransitionMatrix.from_history(records)
        assert mat.total_transitions == 0

    def test_persistence_prob_is_power(self) -> None:
        mat = TransitionMatrix()
        for _ in range(10):
            mat.update_transition("over_forecast", "over_forecast")
        p_ss = mat.probability("over_forecast", "over_forecast")
        assert mat.persistence_prob("over_forecast", 3) == pytest.approx(p_ss ** 3, abs=1e-9)
        assert mat.persistence_prob("over_forecast", 1) == pytest.approx(p_ss, abs=1e-9)

    def test_persistence_prob_k_zero(self) -> None:
        mat = TransitionMatrix()
        assert mat.persistence_prob("accurate", 0) == pytest.approx(1.0)

    def test_stationary_distribution_sums_to_one(self) -> None:
        mat = TransitionMatrix()
        mat.update_transition("accurate", "accurate")
        mat.update_transition("accurate", "over_forecast")
        mat.update_transition("over_forecast", "accurate")
        dist = mat.stationary_distribution()
        assert sum(dist.values()) == pytest.approx(1.0, abs=1e-9)

    def test_stationary_distribution_empty_matrix(self) -> None:
        mat = TransitionMatrix()
        dist = mat.stationary_distribution()
        for state in MARKOV_STATES:
            assert dist[state] == pytest.approx(1.0 / 3, abs=1e-4)

    def test_stationary_absorbing_state(self) -> None:
        """If a state always self-loops, it dominates the stationary dist."""
        mat = TransitionMatrix()
        for _ in range(100):
            mat.update_transition("over_forecast", "over_forecast")
        dist = mat.stationary_distribution()
        assert dist["over_forecast"] > 0.5

    def test_incremental_update_equivalent_to_batch(self) -> None:
        records = _records_sequence("S1", [
            "accurate", "over_forecast", "over_forecast", "accurate",
            "under_forecast", "accurate", "accurate",
        ])
        batch = TransitionMatrix.from_history(records)

        incremental = TransitionMatrix()
        for prev, curr in zip(records, records[1:]):
            incremental.update_transition(prev.direction, curr.direction)

        for s1 in MARKOV_STATES:
            for s2 in MARKOV_STATES:
                assert batch.probability(s1, s2) == pytest.approx(
                    incremental.probability(s1, s2), abs=1e-9
                )

    def test_row_probabilities_matches_individual(self) -> None:
        mat = TransitionMatrix()
        mat.update_transition("accurate", "over_forecast")
        mat.update_transition("accurate", "under_forecast")
        row = mat.row_probabilities("accurate")
        for state in MARKOV_STATES:
            assert row[state] == pytest.approx(mat.probability("accurate", state))

    def test_total_transitions_counts(self) -> None:
        mat = TransitionMatrix()
        assert mat.total_transitions == 0
        mat.update_transition("accurate", "accurate")
        assert mat.total_transitions == 1
        mat.update_transition("over_forecast", "under_forecast")
        assert mat.total_transitions == 2


# ===================================================================
# Helper function tests
# ===================================================================


class TestHelpers:
    def test_consecutive_tail_count_empty(self) -> None:
        assert _consecutive_tail_count([]) == ("", 0)

    def test_consecutive_tail_count_all_same(self) -> None:
        recs = _records_sequence("S1", ["over_forecast"] * 5)
        assert _consecutive_tail_count(recs) == ("over_forecast", 5)

    def test_consecutive_tail_count_mixed(self) -> None:
        recs = _records_sequence("S1", [
            "accurate", "over_forecast", "over_forecast", "under_forecast",
        ])
        assert _consecutive_tail_count(recs) == ("under_forecast", 1)

    def test_consecutive_tail_count_transition_at_end(self) -> None:
        recs = _records_sequence("S1", [
            "accurate", "accurate", "over_forecast", "over_forecast",
        ])
        assert _consecutive_tail_count(recs) == ("over_forecast", 2)

    def test_kl_divergence_identical_distributions(self) -> None:
        p = {"a": 0.5, "b": 0.3, "c": 0.2}
        assert _kl_divergence(p, p) == pytest.approx(0.0, abs=1e-9)

    def test_kl_divergence_different_distributions(self) -> None:
        p = {"a": 0.8, "b": 0.1, "c": 0.1}
        q = {"a": 0.33, "b": 0.33, "c": 0.34}
        assert _kl_divergence(p, q) > 0


# ===================================================================
# MarkovDriftContext tests
# ===================================================================


class TestMarkovDriftContext:
    def test_is_subclass_of_drift_context(self) -> None:
        ctx = _build_markov_ctx({})
        assert isinstance(ctx, DriftContext)

    def test_carries_residual_history(self) -> None:
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", ["accurate"] * 5)}
        ctx = _build_markov_ctx(history)
        assert len(ctx.residual_history["VG-TEST-001"]) == 5

    def test_default_config_values(self) -> None:
        ctx = _build_markov_ctx({})
        assert ctx.min_weeks == 4
        assert ctx.persistence_threshold == 3
        assert ctx.max_history_weeks == 52

    def test_custom_config_values(self) -> None:
        ctx = _build_markov_ctx({}, min_weeks=8, persistence_threshold=5)
        assert ctx.min_weeks == 8
        assert ctx.persistence_threshold == 5


# ===================================================================
# markov_strategy tests
# ===================================================================


class TestMarkovStrategy:
    def test_plain_drift_context_returns_empty_report(self) -> None:
        """Non-MarkovDriftContext should get an empty report."""
        fc = _demand_line()
        ctx = DriftContext(
            forecast_lines=[fc],
            actuals_lines=[],
            mappings_by_key={},
            products_by_sku={},
            iso_week_forecast="2026-W20",
            iso_week_actuals="2026-W19",
            threshold_low=0.5,
            threshold_high=1.5,
            residual_threshold=0.10,
        )
        report = markov_strategy(ctx)
        assert report.mode == "markov"
        assert len(report.signals) == 0

    def test_insufficient_data_skip(self) -> None:
        """SKU with < min_weeks history should be skipped."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", ["accurate"] * 2)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        report = markov_strategy(ctx)
        assert len(report.signals) == 1
        assert report.signals[0].direction == "skipped_insufficient_data"
        assert "need >= 4" in report.signals[0].reason

    def test_4_week_stable_history(self) -> None:
        """4 weeks of 'accurate' should be stable."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", ["accurate"] * 4)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        report = markov_strategy(ctx)
        stable = [s for s in report.signals if s.direction == "stable"]
        assert len(stable) == 1

    def test_persistence_detected_over_forecast(self) -> None:
        """3+ consecutive over_forecast weeks triggers persistence."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", [
            "accurate", "over_forecast", "over_forecast", "over_forecast", "over_forecast",
        ])}
        ctx = _build_markov_ctx(history, min_weeks=4, persistence_threshold=3)
        report = markov_strategy(ctx)
        persist = [s for s in report.signals if s.direction == "persistent_over"]
        assert len(persist) == 1
        assert persist[0].persistence_weeks == 4
        assert persist[0].transition_probability is not None

    def test_persistence_detected_under_forecast(self) -> None:
        """3+ consecutive under_forecast weeks triggers persistence."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", [
            "accurate", "under_forecast", "under_forecast", "under_forecast",
        ])}
        ctx = _build_markov_ctx(history, min_weeks=4, persistence_threshold=3)
        report = markov_strategy(ctx)
        persist = [s for s in report.signals if s.direction == "persistent_under"]
        assert len(persist) == 1
        assert persist[0].persistence_weeks == 3

    def test_no_persistence_below_threshold(self) -> None:
        """2 consecutive over_forecast with threshold=3 should NOT trigger."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", [
            "accurate", "accurate", "over_forecast", "over_forecast",
        ])}
        ctx = _build_markov_ctx(history, min_weeks=4, persistence_threshold=3)
        report = markov_strategy(ctx)
        persist = [s for s in report.signals if "persistent" in s.direction]
        assert len(persist) == 0

    def test_8_week_history_stable(self) -> None:
        """8 weeks alternating states should be stable."""
        pattern = ["accurate", "over_forecast"] * 4
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", pattern)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        report = markov_strategy(ctx)
        assert any(s.direction == "stable" for s in report.signals)

    def test_12_week_regime_drift(self) -> None:
        """SKU with extreme bias vs population should show regime_drift."""
        history = {
            "VG-TEST-001": _records_sequence("VG-TEST-001", ["under_forecast"] * 12),
            "VG-OTHER-001": _records_sequence("VG-OTHER-001", ["accurate"] * 12),
        }
        fc1 = _demand_line("Test Product")
        fc2 = _demand_line("Other Product")
        m1 = _mapping("Test Product", "VG-TEST-001")
        m2 = _mapping("Other Product", "VG-OTHER-001")

        ctx = MarkovDriftContext(
            forecast_lines=[fc1, fc2],
            actuals_lines=[],
            mappings_by_key={fc1.retailer_key.model_dump_json(): m1, fc2.retailer_key.model_dump_json(): m2},
            products_by_sku={"VG-TEST-001": _product("VG-TEST-001"), "VG-OTHER-001": _product("VG-OTHER-001")},
            iso_week_forecast="2026-W20",
            iso_week_actuals="2026-W19",
            threshold_low=0.5,
            threshold_high=1.5,
            residual_threshold=0.10,
            residual_history=history,
            min_weeks=4,
            persistence_threshold=3,
        )
        report = markov_strategy(ctx)
        test_sig = [s for s in report.signals if s.erp_sku == "VG-TEST-001"]
        assert len(test_sig) == 1
        assert test_sig[0].direction in ("persistent_under", "regime_drift")

    def test_52_week_long_history(self) -> None:
        """Strategy handles 52-week histories correctly."""
        pattern = (["accurate"] * 10 + ["over_forecast"] * 5) * 3 + ["accurate"] * 7
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", pattern)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        report = markov_strategy(ctx)
        assert len(report.signals) == 1
        assert report.signals[0].direction in ("stable", "regime_drift")

    def test_summary_counts(self) -> None:
        """Summary dict has correct category counts."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", ["accurate"] * 6)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        report = markov_strategy(ctx)
        assert report.summary.get("stable", 0) + report.summary.get("regime_drift", 0) >= 1

    def test_unmapped_skus_skipped(self) -> None:
        """Forecast lines without resolved mappings are silently skipped."""
        fc = _demand_line("Unknown Product")
        ctx = MarkovDriftContext(
            forecast_lines=[fc],
            actuals_lines=[],
            mappings_by_key={},
            products_by_sku={},
            iso_week_forecast="2026-W20",
            iso_week_actuals="2026-W19",
            threshold_low=0.5,
            threshold_high=1.5,
            residual_threshold=0.10,
            residual_history={},
            min_weeks=4,
            persistence_threshold=3,
        )
        report = markov_strategy(ctx)
        assert report.summary.get("skipped_unmapped", 0) == 1

    def test_signal_fields_populated(self) -> None:
        """DriftSignal for Markov should have persistence_weeks and transition_probability."""
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", ["accurate"] * 6)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        report = markov_strategy(ctx)
        sig = report.signals[0]
        assert sig.persistence_weeks is not None
        assert sig.transition_probability is not None
        assert sig.mode == "markov"


# ===================================================================
# DriftAnalyzer dispatch tests
# ===================================================================


class TestDriftAnalyzerMarkov:
    def test_markov_registered_in_default_strategies(self) -> None:
        analyzer = DriftAnalyzer()
        assert "markov" in analyzer.available_modes

    def test_dispatch_calls_markov_strategy(self) -> None:
        history = {"VG-TEST-001": _records_sequence("VG-TEST-001", ["accurate"] * 5)}
        ctx = _build_markov_ctx(history, min_weeks=4)
        analyzer = DriftAnalyzer()
        report = analyzer.analyze("markov", ctx)
        assert report.mode == "markov"


# ===================================================================
# Repository residual history tests
# ===================================================================


class TestResidualRepository:
    def test_save_and_get_roundtrip(self) -> None:
        repo = InMemoryRepository()
        rec = _record("S1", "2026-W10", "accurate", 0.02)
        repo.save_residual_history(rec)
        result = repo.get_residual_history("S1")
        assert len(result) == 1
        assert result[0].erp_sku == "S1"

    def test_get_empty_returns_empty(self) -> None:
        repo = InMemoryRepository()
        assert repo.get_residual_history("NOEXIST") == []

    def test_bounded_by_max_weeks(self) -> None:
        repo = InMemoryRepository()
        for i in range(10):
            repo.save_residual_history(
                _record("S1", f"2026-W{10 + i:02d}", "accurate", 0.01)
            )
        result = repo.get_residual_history("S1", max_weeks=5)
        assert len(result) == 5
        assert result[0].iso_week == "2026-W15"

    def test_max_weeks_zero_returns_empty(self) -> None:
        repo = InMemoryRepository()
        repo.save_residual_history(_record("S1", "2026-W10", "accurate", 0.01))
        assert repo.get_residual_history("S1", max_weeks=0) == []

    def test_multiple_skus_independent(self) -> None:
        repo = InMemoryRepository()
        repo.save_residual_history(_record("S1", "2026-W10", "accurate", 0.01))
        repo.save_residual_history(_record("S2", "2026-W10", "over_forecast", 0.15))
        assert len(repo.get_residual_history("S1")) == 1
        assert len(repo.get_residual_history("S2")) == 1
        assert repo.get_residual_history("S1")[0].direction == "accurate"
        assert repo.get_residual_history("S2")[0].direction == "over_forecast"


# ===================================================================
# Config parsing tests
# ===================================================================


class TestMarkovConfig:
    def test_default_markov_settings(self) -> None:
        cfg = Settings(
            erp_api_key="test-key",
            _env_file=None,
        )
        assert cfg.drift_markov_min_weeks == 4
        assert cfg.drift_markov_persistence_threshold == 3
        assert cfg.drift_markov_max_weeks == 52

    def test_custom_markov_settings(self) -> None:
        cfg = Settings(
            erp_api_key="test-key",
            drift_markov_min_weeks=8,
            drift_markov_persistence_threshold=5,
            drift_markov_max_weeks=26,
            _env_file=None,
        )
        assert cfg.drift_markov_min_weeks == 8
        assert cfg.drift_markov_persistence_threshold == 5
        assert cfg.drift_markov_max_weeks == 26
