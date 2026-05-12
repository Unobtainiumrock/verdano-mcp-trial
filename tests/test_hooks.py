"""Tests for post-calibration confidence hooks (D-022).

Covers the ConfidenceHook system and the temperature_band_penalty hook.
"""

from __future__ import annotations

import pytest

from verdano.erp.models import Product
from verdano.mapping.hooks import (
    ConfidenceHook,
    DEFAULT_HOOKS,
    temperature_band_penalty,
)


def _product(
    sku: str = "SKU-001",
    name: str = "Verdano Spicy Chorizo 200g",
    band: str = "ambient",
) -> Product:
    return Product(
        sku=sku,
        name=name,
        category="Deli",
        temperature_band=band,
        case_pack=6,
        current_gtins=["1234567890123"],
        legacy_gtins=[],
        aliases=[],
        status="active",
    )


class TestDefaultHooks:
    def test_default_hooks_is_empty(self) -> None:
        assert DEFAULT_HOOKS == []

    def test_no_hooks_preserves_confidence(self) -> None:
        products = {"SKU-001": _product()}
        confidence = 0.95
        for hook in DEFAULT_HOOKS:
            confidence = hook(confidence, "SKU-001", products)
        assert confidence == 0.95


class TestTemperatureBandPenalty:
    def test_no_mismatch_no_penalty(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product(band="ambient")}
        result = hook(0.95, "SKU-001", products)
        assert result == 0.95

    def test_chilled_keyword_in_ambient_product_penalized(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product(name="Fresh Chilled Chicken Breast", band="ambient")}
        result = hook(0.95, "SKU-001", products)
        assert result == pytest.approx(0.95 * 0.3)

    def test_frozen_keyword_in_chilled_product_penalized(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.5)
        products = {"SKU-001": _product(name="Frozen Peas 500g", band="chilled")}
        result = hook(0.95, "SKU-001", products)
        assert result == pytest.approx(0.95 * 0.5)

    def test_ambient_keyword_in_chilled_product_penalized(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product(name="Long Life UHT Milk 1L", band="chilled")}
        result = hook(0.95, "SKU-001", products)
        assert result == pytest.approx(0.95 * 0.3)

    def test_matching_keyword_and_band_no_penalty(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product(name="Fresh Chilled Chorizo 200g", band="chilled")}
        result = hook(0.95, "SKU-001", products)
        assert result == 0.95

    def test_unknown_sku_no_penalty(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product()}
        result = hook(0.95, "UNKNOWN", products)
        assert result == 0.95

    def test_custom_lambda(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.1)
        products = {"SKU-001": _product(name="Frozen Beef Burgers", band="ambient")}
        result = hook(0.90, "SKU-001", products)
        assert result == pytest.approx(0.90 * 0.1)

    def test_penalty_pushes_below_auto_threshold(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product(name="Chilled Salmon Fillets", band="ambient")}
        result = hook(0.95, "SKU-001", products)
        assert result < 0.90

    def test_case_insensitive_keywords(self) -> None:
        hook = temperature_band_penalty(lambda_penalty=0.3)
        products = {"SKU-001": _product(name="FROZEN FISH FINGERS 10PK", band="ambient")}
        result = hook(0.95, "SKU-001", products)
        assert result == pytest.approx(0.95 * 0.3)


class TestHookComposition:
    def test_multiple_hooks_multiply(self) -> None:
        hook1 = temperature_band_penalty(lambda_penalty=0.5)

        def half_hook(confidence: float, sku: str, products: dict[str, Product]) -> float:
            return confidence * 0.5

        products = {"SKU-001": _product(name="Frozen Chorizo", band="ambient")}
        confidence = 0.95
        for hook in [hook1, half_hook]:
            confidence = hook(confidence, "SKU-001", products)
        assert confidence == pytest.approx(0.95 * 0.5 * 0.5)

    def test_identity_hook_no_effect(self) -> None:
        def identity_hook(confidence: float, sku: str, products: dict[str, Product]) -> float:
            return confidence

        products = {"SKU-001": _product()}
        result = identity_hook(0.85, "SKU-001", products)
        assert result == 0.85


class TestHookInResolverContext:
    def test_build_result_applies_hooks(self) -> None:
        from verdano.mapping.resolver import MasterIndex, ResolverContext

        product = _product(sku="SKU-001", name="Frozen Peas", band="ambient")
        master = MasterIndex([product])
        hook = temperature_band_penalty(lambda_penalty=0.3)

        from verdano.mapping.priors import DEFAULT_PRIORS

        ctx = ResolverContext(
            master=master,
            priors=DEFAULT_PRIORS,
            auto_threshold=0.90,
            tfidf_min_score=0.5,
            tfidf_min_matched_tokens=2,
            fuzzy_jw_min_score=0.30,
            confidence_hooks=[hook],
        )
        from verdano.canonical import RetailerProductKey

        key = RetailerProductKey(retailer="tesco", name="Frozen Peas", gtin="1234567890123")
        result = ctx.build_result(key, "SKU-001", 0.95, "gtin_current", "1234567890123", 1)
        assert result.confidence == pytest.approx(0.95 * 0.3)
        assert result.state == "NeedsVerification"

    def test_build_result_no_hooks_preserves_behavior(self) -> None:
        from verdano.mapping.resolver import MasterIndex, ResolverContext

        product = _product(sku="SKU-001")
        master = MasterIndex([product])

        from verdano.mapping.priors import DEFAULT_PRIORS

        ctx = ResolverContext(
            master=master,
            priors=DEFAULT_PRIORS,
            auto_threshold=0.90,
            tfidf_min_score=0.5,
            tfidf_min_matched_tokens=2,
            fuzzy_jw_min_score=0.30,
        )
        from verdano.canonical import RetailerProductKey

        key = RetailerProductKey(retailer="tesco", name="Spicy Chorizo", gtin="1234567890123")
        result = ctx.build_result(key, "SKU-001", 0.95, "gtin_current", "1234567890123", 1)
        assert result.confidence == 0.95
        assert result.state == "Resolved"


class TestConfigIntegration:
    def test_config_default_disabled(self) -> None:
        import os
        env = {
            "VERDANO_ERP_API_KEY": "test-key",
            "VERDANO_TEMP_BAND_PENALTY_ENABLED": "false",
        }
        for k, v in env.items():
            os.environ[k] = v
        try:
            from verdano.config import Settings
            cfg = Settings()
            assert cfg.temp_band_penalty_enabled is False
            assert cfg.temp_band_penalty_lambda == 0.3
        finally:
            for k in env:
                os.environ.pop(k, None)

    def test_config_enabled_with_custom_lambda(self) -> None:
        import os
        env = {
            "VERDANO_ERP_API_KEY": "test-key",
            "VERDANO_TEMP_BAND_PENALTY_ENABLED": "true",
            "VERDANO_TEMP_BAND_PENALTY_LAMBDA": "0.5",
        }
        for k, v in env.items():
            os.environ[k] = v
        try:
            from verdano.config import Settings
            cfg = Settings()
            assert cfg.temp_band_penalty_enabled is True
            assert cfg.temp_band_penalty_lambda == 0.5
        finally:
            for k in env:
                os.environ.pop(k, None)
