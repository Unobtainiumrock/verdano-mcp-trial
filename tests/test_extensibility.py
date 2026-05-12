"""Tests for P2 extensibility scaffolding (D-021).

Covers the three protocol-based extension points:
  1. Calibrator (mapping confidence calibration)
  2. KernelLearner (DOW disaggregation kernel learning)
  3. Repository (persistence layer)
"""

from __future__ import annotations

import pytest

from verdano.adapters.kernel import (
    DEFAULT_KERNEL_LEARNER,
    KernelLearner,
    NNLSKernelLearner,
    StaticKernelLearner,
)
from verdano.adapters.spec import DEFAULT_DOW_KERNEL, DOWKernel
from verdano.canonical import MappingEvidence, MappingResult, RetailerProductKey
from verdano.mapping.calibration import (
    DEFAULT_CALIBRATOR,
    Calibrator,
    SupervisedCalibrator,
    UnsupervisedCalibrator,
)
from verdano.storage import (
    AuditEntry,
    DuckDBRepository,
    InMemoryRepository,
    Repository,
    ReviewLabel,
)


# ──────────────────────────────────────────────────────────────────
# 1. Calibrator
# ──────────────────────────────────────────────────────────────────


class TestCalibratorProtocol:
    def test_unsupervised_satisfies_protocol(self) -> None:
        assert isinstance(UnsupervisedCalibrator(), Calibrator)

    def test_supervised_satisfies_protocol(self) -> None:
        assert isinstance(SupervisedCalibrator(), Calibrator)

    def test_default_is_unsupervised(self) -> None:
        assert isinstance(DEFAULT_CALIBRATOR, UnsupervisedCalibrator)


class TestUnsupervisedCalibrator:
    def test_clamp_normal_score(self) -> None:
        cal = UnsupervisedCalibrator()
        assert cal.calibrate(0.85, "gtin_current", 1) == 0.85

    def test_clamp_above_one(self) -> None:
        cal = UnsupervisedCalibrator()
        assert cal.calibrate(1.5, "alias_exact", 2) == 1.0

    def test_clamp_below_zero(self) -> None:
        cal = UnsupervisedCalibrator()
        assert cal.calibrate(-0.3, "fuzzy_jw", 1) == 0.0

    def test_boundary_values(self) -> None:
        cal = UnsupervisedCalibrator()
        assert cal.calibrate(0.0, "gtin_current", 1) == 0.0
        assert cal.calibrate(1.0, "gtin_current", 1) == 1.0


class TestSupervisedCalibrator:
    def test_raises_not_implemented(self) -> None:
        cal = SupervisedCalibrator()
        with pytest.raises(NotImplementedError, match="trained model"):
            cal.calibrate(0.85, "gtin_current", 1)

    def test_accepts_model_path(self) -> None:
        cal = SupervisedCalibrator(model_path="/tmp/model.pkl")
        assert cal._model_path == "/tmp/model.pkl"


class TestCustomCalibrator:
    def test_custom_calibrator_plugs_in(self) -> None:
        class FixedCalibrator:
            def calibrate(self, score: float, stratum: str, k_x: int) -> float:
                return 0.42

        cal = FixedCalibrator()
        assert isinstance(cal, Calibrator)
        assert cal.calibrate(0.99, "gtin_current", 1) == 0.42


# ──────────────────────────────────────────────────────────────────
# 2. KernelLearner
# ──────────────────────────────────────────────────────────────────


class TestKernelLearnerProtocol:
    def test_static_satisfies_protocol(self) -> None:
        assert isinstance(StaticKernelLearner(), KernelLearner)

    def test_nnls_satisfies_protocol(self) -> None:
        assert isinstance(NNLSKernelLearner(), KernelLearner)

    def test_default_is_static(self) -> None:
        assert isinstance(DEFAULT_KERNEL_LEARNER, StaticKernelLearner)


class TestStaticKernelLearner:
    def test_returns_default_kernel(self) -> None:
        learner = StaticKernelLearner()
        kernel = learner.learn("tesco")
        assert kernel.weights == DEFAULT_DOW_KERNEL

    def test_custom_weights(self) -> None:
        custom: tuple[float, ...] = (1 / 7,) * 7
        learner = StaticKernelLearner(default_weights=custom)  # type: ignore[arg-type]
        kernel = learner.learn("sainsburys")
        assert abs(sum(kernel.weights) - 1.0) < 1e-6

    def test_same_kernel_for_any_retailer(self) -> None:
        learner = StaticKernelLearner()
        assert learner.learn("tesco") == learner.learn("sainsburys")


class TestNNLSKernelLearner:
    def test_raises_not_implemented(self) -> None:
        learner = NNLSKernelLearner()
        with pytest.raises(NotImplementedError, match="EPOS data"):
            learner.learn("tesco")

    def test_custom_min_weeks(self) -> None:
        learner = NNLSKernelLearner(min_weeks=8)
        with pytest.raises(NotImplementedError, match="8 weeks"):
            learner.learn("tesco")


class TestCustomKernelLearner:
    def test_custom_learner_plugs_in(self) -> None:
        class UniformLearner:
            def learn(self, retailer_code: str) -> DOWKernel:
                w = tuple(1 / 7 for _ in range(7))
                return DOWKernel(weights=w)  # type: ignore[arg-type]

        learner = UniformLearner()
        assert isinstance(learner, KernelLearner)
        kernel = learner.learn("test")
        assert abs(sum(kernel.weights) - 1.0) < 1e-6


# ──────────────────────────────────────────────────────────────────
# 3. Repository
# ──────────────────────────────────────────────────────────────────


def _sample_mapping_result() -> MappingResult:
    return MappingResult(
        retailer_key=RetailerProductKey(
            retailer="tesco", name="Test Product", gtin="1234567890123",
        ),
        erp_sku="SKU-001",
        confidence=0.95,
        state="Resolved",
        evidence=MappingEvidence(
            stratum="gtin_current",
            matched_value="1234567890123",
            collision_count=1,
        ),
    )


class TestRepositoryProtocol:
    def test_inmemory_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryRepository(), Repository)

    def test_duckdb_satisfies_protocol(self) -> None:
        assert isinstance(DuckDBRepository(), Repository)


class TestInMemoryRepository:
    def test_mapping_roundtrip(self) -> None:
        repo = InMemoryRepository()
        result = _sample_mapping_result()
        repo.save_mapping(result)
        fetched = repo.get_mapping("Test Product")
        assert fetched is not None
        assert fetched.erp_sku == "SKU-001"
        assert fetched.confidence == 0.95
        assert fetched.state == "Resolved"
        assert fetched.retailer_key.name == "Test Product"
        assert fetched.evidence is not None
        assert fetched.evidence.stratum == "gtin_current"

    def test_mapping_miss_returns_none(self) -> None:
        repo = InMemoryRepository()
        assert repo.get_mapping("nonexistent") is None

    def test_mapping_overwrite(self) -> None:
        repo = InMemoryRepository()
        r1 = _sample_mapping_result()
        repo.save_mapping(r1)
        r2 = MappingResult(
            retailer_key=RetailerProductKey(
                retailer="tesco", name="Test Product", gtin="9999",
            ),
            erp_sku="SKU-002",
            confidence=0.80,
            state="Resolved",
            evidence=MappingEvidence(
                stratum="alias_exact",
                matched_value="Test Product",
                collision_count=1,
            ),
        )
        repo.save_mapping(r2)
        assert repo.get_mapping("Test Product").erp_sku == "SKU-002"  # type: ignore[union-attr]

    def test_review_labels_roundtrip(self) -> None:
        repo = InMemoryRepository()
        label = ReviewLabel(
            retailer_key_name="Foo Bar",
            corrected_erp_sku="SKU-CORRECT",
            reviewer="alice",
        )
        repo.save_review_label(label)
        assert repo.count_review_labels() == 1
        labels = repo.get_review_labels()
        assert labels[0].corrected_erp_sku == "SKU-CORRECT"

    def test_review_labels_count(self) -> None:
        repo = InMemoryRepository()
        for i in range(5):
            repo.save_review_label(ReviewLabel(
                retailer_key_name=f"Product {i}",
                corrected_erp_sku=f"SKU-{i}",
            ))
        assert repo.count_review_labels() == 5

    def test_audit_log_roundtrip(self) -> None:
        repo = InMemoryRepository()
        entry = AuditEntry(
            tool_name="analyze_week_fulfillment",
            retailer="tesco",
            iso_week="2026-W20",
            summary="10 lines classified",
        )
        repo.log_audit(entry)
        log = repo.get_audit_log()
        assert len(log) == 1
        assert log[0].tool_name == "analyze_week_fulfillment"

    def test_audit_log_most_recent_first(self) -> None:
        repo = InMemoryRepository()
        for i in range(3):
            repo.log_audit(AuditEntry(
                tool_name=f"tool_{i}",
                retailer="tesco",
                iso_week="2026-W20",
            ))
        log = repo.get_audit_log()
        assert log[0].tool_name == "tool_2"
        assert log[2].tool_name == "tool_0"

    def test_audit_log_limit(self) -> None:
        repo = InMemoryRepository()
        for i in range(10):
            repo.log_audit(AuditEntry(
                tool_name=f"tool_{i}",
                retailer="tesco",
                iso_week="2026-W20",
            ))
        log = repo.get_audit_log(limit=3)
        assert len(log) == 3
        assert log[0].tool_name == "tool_9"
        assert log[2].tool_name == "tool_7"

    def test_audit_log_limit_zero_returns_empty(self) -> None:
        repo = InMemoryRepository()
        repo.log_audit(AuditEntry(
            tool_name="x", retailer="y", iso_week="z",
        ))
        assert repo.get_audit_log(limit=0) == []

    def test_empty_repo_returns_empty(self) -> None:
        repo = InMemoryRepository()
        assert repo.get_mapping("anything") is None
        assert repo.get_review_labels() == []
        assert repo.count_review_labels() == 0
        assert repo.get_audit_log() == []

    def test_review_label_full_fields_roundtrip(self) -> None:
        repo = InMemoryRepository()
        label = ReviewLabel(
            retailer_key_name="Foo Bar",
            retailer_key_gtin="1234567890123",
            original_erp_sku="SKU-OLD",
            corrected_erp_sku="SKU-NEW",
            reviewer="bob",
        )
        repo.save_review_label(label)
        fetched = repo.get_review_labels()[0]
        assert fetched.retailer_key_name == "Foo Bar"
        assert fetched.retailer_key_gtin == "1234567890123"
        assert fetched.original_erp_sku == "SKU-OLD"
        assert fetched.corrected_erp_sku == "SKU-NEW"
        assert fetched.reviewer == "bob"


class TestDuckDBRepository:
    def test_save_mapping_raises(self) -> None:
        repo = DuckDBRepository()
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            repo.save_mapping(_sample_mapping_result())

    def test_get_mapping_raises(self) -> None:
        repo = DuckDBRepository()
        with pytest.raises(NotImplementedError, match="not yet implemented"):
            repo.get_mapping("anything")

    def test_review_labels_raise(self) -> None:
        repo = DuckDBRepository()
        with pytest.raises(NotImplementedError):
            repo.save_review_label(ReviewLabel(
                retailer_key_name="x", corrected_erp_sku="y",
            ))
        with pytest.raises(NotImplementedError):
            repo.get_review_labels()
        with pytest.raises(NotImplementedError):
            repo.count_review_labels()

    def test_audit_log_raises(self) -> None:
        repo = DuckDBRepository()
        with pytest.raises(NotImplementedError):
            repo.log_audit(AuditEntry(
                tool_name="x", retailer="y", iso_week="z",
            ))
        with pytest.raises(NotImplementedError):
            repo.get_audit_log()

    def test_custom_db_path(self) -> None:
        repo = DuckDBRepository(db_path="/tmp/custom.duckdb")
        assert repo._db_path == "/tmp/custom.duckdb"


class TestCustomRepository:
    def test_custom_repo_plugs_in(self) -> None:
        class NoOpRepository:
            def save_mapping(self, result: MappingResult) -> None:
                pass

            def get_mapping(self, retailer_key_name: str) -> MappingResult | None:
                return None

            def save_review_label(self, label: ReviewLabel) -> None:
                pass

            def get_review_labels(self) -> list[ReviewLabel]:
                return []

            def count_review_labels(self) -> int:
                return 0

            def log_audit(self, entry: AuditEntry) -> None:
                pass

            def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
                return []

            def save_residual_history(self, record: object) -> None:
                pass

            def get_residual_history(
                self, erp_sku: str, max_weeks: int = 52
            ) -> list:
                return []

        assert isinstance(NoOpRepository(), Repository)
