"""Tests for the LLM post-cascade re-ranker (D-019). Fully mocked — no API calls."""

from __future__ import annotations

import json
from typing import Any

import pytest

from cpg_reconciler.canonical import MappingEvidence, MappingResult, RetailerProductKey
from cpg_reconciler.erp.models import Product
from cpg_reconciler.llm.reranker import (
    ReRankResult,
    apply_rerank,
    rerank_mapping,
    should_rerank,
)
from cpg_reconciler.mapping.resolver import MasterIndex


class FakeLLMClient:
    """Test double implementing the LLMClient protocol."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return self._response


class FailingLLMClient:
    """Test double that always raises."""

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        raise RuntimeError("API unreachable")


_PRODUCTS = [
    Product(
        sku="VG-FALA-350",
        name="Falafel Bowl 350g",
        category="meals",
        status="active",
        current_gtins=[],
        legacy_gtins=[],
        aliases=["Falafel Bowl"],
        case_pack=6,
        temperature_band="chilled",
    ),
    Product(
        sku="VG-FALA-500",
        name="Falafel Bowl 500g",
        category="meals",
        status="active",
        current_gtins=[],
        legacy_gtins=[],
        aliases=["Falafel Bowl Large"],
        case_pack=4,
        temperature_band="chilled",
    ),
    Product(
        sku="VG-SOUP-400",
        name="Tomato Basil Soup 400g",
        category="soup",
        status="active",
        current_gtins=[],
        legacy_gtins=[],
        aliases=[],
        case_pack=6,
        temperature_band="ambient",
    ),
]


def _master() -> MasterIndex:
    return MasterIndex(_PRODUCTS)


def _mapping(
    *,
    sku: str = "VG-FALA-350",
    confidence: float = 0.75,
    state: str = "Resolved",
    stratum: str = "fuzzy_jw",
    name: str = "Falafel Bowl Large",
) -> MappingResult:
    return MappingResult(
        retailer_key=RetailerProductKey(retailer="tesco", name=name),
        erp_sku=sku,
        confidence=confidence,
        state=state,
        evidence=MappingEvidence(stratum=stratum, matched_value=name, collision_count=1),
    )


# ---------------------------------------------------------------------------
# should_rerank
# ---------------------------------------------------------------------------


class TestShouldRerank:
    def test_unmapped_skipped(self) -> None:
        m = MappingResult(
            retailer_key=RetailerProductKey(retailer="tesco", name="x"),
            erp_sku=None,
            confidence=0.0,
            state="Unmapped",
            evidence=None,
        )
        assert not should_rerank(m, rerank_threshold=0.92, rerank_strata=frozenset({"fuzzy_jw"}))

    def test_high_confidence_gtin_skipped(self) -> None:
        m = _mapping(confidence=0.98, stratum="gtin_current")
        assert not should_rerank(m, rerank_threshold=0.92, rerank_strata=frozenset({"fuzzy_jw"}))

    def test_fuzzy_jw_always_reranked(self) -> None:
        m = _mapping(confidence=0.95, stratum="fuzzy_jw")
        assert should_rerank(m, rerank_threshold=0.92, rerank_strata=frozenset({"fuzzy_jw"}))

    def test_tfidf_always_reranked(self) -> None:
        m = _mapping(confidence=0.95, stratum="tfidf_overlap")
        assert should_rerank(
            m, rerank_threshold=0.92, rerank_strata=frozenset({"tfidf_overlap", "fuzzy_jw"})
        )

    def test_low_confidence_alias_reranked(self) -> None:
        m = _mapping(confidence=0.80, stratum="alias_exact")
        assert should_rerank(m, rerank_threshold=0.92, rerank_strata=frozenset({"fuzzy_jw"}))

    def test_high_confidence_alias_not_reranked(self) -> None:
        m = _mapping(confidence=0.98, stratum="alias_exact")
        assert not should_rerank(m, rerank_threshold=0.92, rerank_strata=frozenset({"fuzzy_jw"}))


# ---------------------------------------------------------------------------
# rerank_mapping — LLM agrees
# ---------------------------------------------------------------------------


class TestReRankAgrees:
    def test_llm_agrees_returns_agrees_true(self) -> None:
        m = _mapping()
        master = _master()
        client = FakeLLMClient(
            json.dumps({"agrees": True, "sku": "VG-FALA-350", "confidence": 0.90, "reason": "ok"})
        )
        rr = rerank_mapping(m, master, client)
        assert rr.agrees is True
        assert rr.confidence == 0.90

    def test_agreed_mapping_unchanged(self) -> None:
        m = _mapping()
        rr = ReRankResult(agrees=True, suggested_sku=None, confidence=0.9, reason="ok")
        result = apply_rerank(m, rr)
        assert result is m


# ---------------------------------------------------------------------------
# rerank_mapping — LLM disagrees with high confidence
# ---------------------------------------------------------------------------


class TestReRankDisagreesHigh:
    def test_llm_disagrees_high_conf(self) -> None:
        m = _mapping(sku="VG-FALA-350")
        master = _master()
        client = FakeLLMClient(
            json.dumps({
                "agrees": False,
                "sku": "VG-FALA-500",
                "confidence": 0.85,
                "reason": "'Large' indicates the 500g variant",
            })
        )
        rr = rerank_mapping(m, master, client, min_llm_confidence=0.70)
        assert rr.agrees is False
        assert rr.suggested_sku == "VG-FALA-500"
        assert rr.confidence == 0.85

    def test_disagreed_mapping_downgraded(self) -> None:
        m = _mapping(state="Resolved")
        rr = ReRankResult(
            agrees=False,
            suggested_sku="VG-FALA-500",
            confidence=0.85,
            reason="size mismatch",
        )
        result = apply_rerank(m, rr)
        assert result.state == "NeedsVerification"
        assert result.evidence is not None
        assert result.evidence.stratum == "llm_rerank"
        assert result.erp_sku == m.erp_sku


# ---------------------------------------------------------------------------
# rerank_mapping — LLM disagrees with LOW confidence → keep original
# ---------------------------------------------------------------------------


class TestReRankDisagreesLow:
    def test_llm_disagrees_low_conf_treated_as_agree(self) -> None:
        m = _mapping()
        master = _master()
        client = FakeLLMClient(
            json.dumps({
                "agrees": False,
                "sku": "VG-FALA-500",
                "confidence": 0.40,
                "reason": "unsure",
            })
        )
        rr = rerank_mapping(m, master, client, min_llm_confidence=0.70)
        assert rr.agrees is True
        assert "too low" in rr.reason

    def test_low_conf_disagreement_keeps_original(self) -> None:
        m = _mapping(state="Resolved")
        rr = ReRankResult(agrees=True, suggested_sku=None, confidence=0.40, reason="too low")
        result = apply_rerank(m, rr)
        assert result is m


# ---------------------------------------------------------------------------
# rerank_mapping — LLM failure (graceful degradation)
# ---------------------------------------------------------------------------


class TestReRankFailure:
    def test_llm_exception_defaults_to_agree(self) -> None:
        m = _mapping()
        master = _master()
        client = FailingLLMClient()
        rr = rerank_mapping(m, master, client)
        assert rr.agrees is True
        assert "failed" in rr.reason.lower()

    def test_failure_keeps_original_mapping(self) -> None:
        m = _mapping(state="Resolved")
        rr = ReRankResult(agrees=True, suggested_sku=None, confidence=0.0, reason="LLM failed")
        result = apply_rerank(m, rr)
        assert result is m


# ---------------------------------------------------------------------------
# Integration: should_rerank filters correctly before calling rerank
# ---------------------------------------------------------------------------


class TestReRankIntegration:
    def test_high_conf_gtin_never_hits_llm(self) -> None:
        """GTIN matches at 0.98 should never be sent to the re-ranker."""
        m = _mapping(confidence=0.98, stratum="gtin_current")
        assert not should_rerank(
            m, rerank_threshold=0.92, rerank_strata=frozenset({"tfidf_overlap", "fuzzy_jw"})
        )

    def test_full_flow_fuzzy_disagree(self) -> None:
        """End-to-end: fuzzy match → re-rank → disagreement → downgrade."""
        m = _mapping(confidence=0.55, stratum="fuzzy_jw", sku="VG-FALA-350")
        master = _master()

        assert should_rerank(
            m, rerank_threshold=0.92, rerank_strata=frozenset({"fuzzy_jw"})
        )

        client = FakeLLMClient(
            json.dumps({
                "agrees": False,
                "sku": "VG-FALA-500",
                "confidence": 0.88,
                "reason": "retailer said 'Large'",
            })
        )
        rr = rerank_mapping(m, master, client, min_llm_confidence=0.70)
        result = apply_rerank(m, rr)

        assert result.state == "NeedsVerification"
        assert result.evidence is not None
        assert result.evidence.stratum == "llm_rerank"
