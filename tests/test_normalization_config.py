"""Tests for normalization config wiring (D-023).

Covers: config field parsing, build_pipeline construction, MasterIndex +
TfIdfIndex with custom normalizers, and end-to-end resolver behavior.
"""

from __future__ import annotations

import os

import pytest

from cpg_reconciler.erp.models import Product
from cpg_reconciler.mapping.normalize import (
    DEFAULT_PIPELINE,
    NormalizationPipeline,
    build_pipeline,
)
from cpg_reconciler.mapping.resolver import MasterIndex, Resolver
from cpg_reconciler.mapping.tfidf import TfIdfIndex
from cpg_reconciler.canonical import RetailerProductKey


def _product(
    sku: str = "SKU-001",
    name: str = "Verdano Spicy Chorizo 200g",
    aliases: list[str] | None = None,
) -> Product:
    return Product(
        sku=sku,
        name=name,
        category="Deli",
        temperature_band="ambient",
        case_pack=6,
        current_gtins=["1234567890123"],
        legacy_gtins=[],
        aliases=aliases or [],
        status="active",
    )


class TestBuildPipeline:
    def test_no_options_matches_default(self) -> None:
        pipeline = build_pipeline()
        assert pipeline("  Verdano   SPICY  Chorizo 1kg ") == DEFAULT_PIPELINE(
            "  Verdano   SPICY  Chorizo 1kg "
        )

    def test_brand_prefix_stripping(self) -> None:
        pipeline = build_pipeline(brand_prefixes={"verdano", "verdano foods"})
        result = pipeline("Verdano Spicy Chorizo 200g")
        assert "verdano" not in result
        assert "spicy chorizo 200g" == result

    def test_stop_word_removal(self) -> None:
        pipeline = build_pipeline(stop_words={"the", "and", "with"})
        result = pipeline("The Spicy and Hot Chorizo with Peppers")
        assert result == "spicy hot chorizo peppers"

    def test_both_active(self) -> None:
        pipeline = build_pipeline(
            brand_prefixes={"verdano"},
            stop_words={"the", "and"},
        )
        result = pipeline("Verdano The Spicy and Hot Chorizo 1kg")
        assert "verdano" not in result
        assert "the" not in result
        assert "and" not in result
        assert "1000g" in result

    def test_empty_sets_treated_as_inactive(self) -> None:
        pipeline = build_pipeline(brand_prefixes=set(), stop_words=set())
        assert pipeline("Verdano Chorizo 1kg") == DEFAULT_PIPELINE("Verdano Chorizo 1kg")

    def test_brand_stripping_before_size_normalization(self) -> None:
        pipeline = build_pipeline(brand_prefixes={"verdano"})
        result = pipeline("Verdano Hummus 1kg")
        assert result == "hummus 1000g"

    def test_stop_words_after_size_normalization(self) -> None:
        pipeline = build_pipeline(stop_words={"pack"})
        result = pipeline("Chorizo Pack 200g")
        assert result == "chorizo 200g"


class TestMasterIndexWithNormalizer:
    def test_custom_normalizer_used_for_alias_lookup(self) -> None:
        pipeline = build_pipeline(brand_prefixes={"verdano"})
        product = _product(name="Spicy Chorizo 200g", aliases=["Verdano Spicy Chorizo 200g"])
        master = MasterIndex([product], normalizer=pipeline)
        hits = master.lookup_alias("Verdano Spicy Chorizo 200g")
        assert hits == ["SKU-001"]

    def test_custom_normalizer_used_for_fuzzy_search(self) -> None:
        pipeline = build_pipeline(brand_prefixes={"verdano"})
        product = _product(name="Spicy Chorizo 200g")
        master = MasterIndex([product], normalizer=pipeline)
        result = master.fuzzy_search("Verdano Spicy Chorizo 200g")
        assert result is not None
        _, score = result
        assert score == 1.0

    def test_default_normalizer_backward_compatible(self) -> None:
        product = _product()
        master_default = MasterIndex([product])
        master_explicit = MasterIndex([product], normalizer=None)
        assert master_default.lookup_alias("verdano spicy chorizo 200g") == \
               master_explicit.lookup_alias("verdano spicy chorizo 200g")


class TestTfIdfWithNormalizer:
    def test_custom_normalizer_affects_indexing(self) -> None:
        pipeline = build_pipeline(brand_prefixes={"verdano"})
        product = _product(name="Verdano Spicy Chorizo 200g")
        tfidf = TfIdfIndex([product], normalizer=pipeline)
        score_with = tfidf.score("Spicy Chorizo 200g", "SKU-001")
        assert score_with > 0.0

    def test_default_normalizer_backward_compatible(self) -> None:
        product = _product()
        tfidf_default = TfIdfIndex([product])
        tfidf_none = TfIdfIndex([product], normalizer=None)
        assert tfidf_default.score("chorizo", "SKU-001") == \
               tfidf_none.score("chorizo", "SKU-001")


class TestResolverWithNormalizer:
    def test_brand_stripping_improves_alias_match(self) -> None:
        pipeline = build_pipeline(brand_prefixes={"verdano"})
        product = _product(
            name="Spicy Chorizo 200g",
            aliases=["Spicy Chorizo 200g"],
        )
        master = MasterIndex([product], normalizer=pipeline)
        resolver = Resolver(master, auto_threshold=0.90)
        key = RetailerProductKey(
            retailer="tesco",
            name="Verdano Spicy Chorizo 200g",
            gtin=None,
        )
        result = resolver.resolve(key)
        assert result.erp_sku == "SKU-001"
        assert result.evidence is not None
        assert result.evidence.stratum == "alias_exact"

    def test_no_normalizer_uses_default(self) -> None:
        product = _product()
        master = MasterIndex([product])
        resolver = Resolver(master, auto_threshold=0.90)
        key = RetailerProductKey(
            retailer="tesco",
            name="Verdano Spicy Chorizo 200g",
            gtin=None,
        )
        result = resolver.resolve(key)
        assert result.erp_sku == "SKU-001"


class TestConfigParsing:
    def test_default_disabled(self) -> None:
        env = {"CPG_RECONCILER_ERP_API_KEY": "test-key"}
        for k, v in env.items():
            os.environ[k] = v
        try:
            from cpg_reconciler.config import Settings
            cfg = Settings()
            assert cfg.normalize_brand_stripping is False
            assert cfg.normalize_stop_words is False
            assert cfg.get_brand_prefixes() is None
            assert cfg.get_stop_words() is None
        finally:
            for k in env:
                os.environ.pop(k, None)

    def test_brand_stripping_enabled(self) -> None:
        env = {
            "CPG_RECONCILER_ERP_API_KEY": "test-key",
            "CPG_RECONCILER_NORMALIZE_BRAND_STRIPPING": "true",
            "CPG_RECONCILER_BRAND_PREFIXES": "acme,acme foods",
        }
        for k, v in env.items():
            os.environ[k] = v
        try:
            from cpg_reconciler.config import Settings
            cfg = Settings()
            assert cfg.normalize_brand_stripping is True
            prefixes = cfg.get_brand_prefixes()
            assert prefixes == {"acme", "acme foods"}
        finally:
            for k in env:
                os.environ.pop(k, None)

    def test_stop_words_enabled(self) -> None:
        env = {
            "CPG_RECONCILER_ERP_API_KEY": "test-key",
            "CPG_RECONCILER_NORMALIZE_STOP_WORDS": "true",
            "CPG_RECONCILER_STOP_WORDS": "the,a,an",
        }
        for k, v in env.items():
            os.environ[k] = v
        try:
            from cpg_reconciler.config import Settings
            cfg = Settings()
            assert cfg.normalize_stop_words is True
            stops = cfg.get_stop_words()
            assert stops == {"the", "a", "an"}
        finally:
            for k in env:
                os.environ.pop(k, None)

    def test_both_enabled_independently(self) -> None:
        env = {
            "CPG_RECONCILER_ERP_API_KEY": "test-key",
            "CPG_RECONCILER_NORMALIZE_BRAND_STRIPPING": "true",
            "CPG_RECONCILER_NORMALIZE_STOP_WORDS": "false",
        }
        for k, v in env.items():
            os.environ[k] = v
        try:
            from cpg_reconciler.config import Settings
            cfg = Settings()
            assert cfg.get_brand_prefixes() is not None
            assert cfg.get_stop_words() is None
        finally:
            for k in env:
                os.environ.pop(k, None)
