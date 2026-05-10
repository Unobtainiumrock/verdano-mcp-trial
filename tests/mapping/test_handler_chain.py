"""Tests for the stratum handler chain architecture."""

from __future__ import annotations

from verdano.canonical import MappingResult, RetailerProductKey
from verdano.erp.models import Product
from verdano.mapping.resolver import (
    DEFAULT_HANDLERS,
    MasterIndex,
    Resolver,
    ResolverContext,
    StratumHandler,
)
from verdano.mapping.priors import DEFAULT_PRIORS


def _make_products() -> list[Product]:
    return [
        Product(
            sku="VG-FALA-300",
            name="Falafel Bowl 300g",
            category="ready meals",
            status="active",
            current_gtins=["5000001"],
            legacy_gtins=[],
            aliases=["Falafel Bowl"],
            case_pack=6,
            temperature_band="chilled",
        ),
    ]


class TestHandlerChain:
    def test_default_handlers_registered(self) -> None:
        names = [name for name, _ in DEFAULT_HANDLERS]
        assert names == ["gtin_current", "gtin_legacy", "alias_exact", "tfidf_overlap", "fuzzy_jw"]

    def test_custom_handler_short_circuits(self) -> None:
        """A custom handler that always returns a result bypasses all defaults."""
        products = _make_products()
        master = MasterIndex(products)

        def always_match(
            ctx: ResolverContext, key: RetailerProductKey
        ) -> MappingResult | None:
            return ctx.build_result(key, "VG-FALA-300", 0.99, "custom", key.name, 1)

        resolver = Resolver(
            master,
            handlers=[("custom", always_match)],
        )

        key = RetailerProductKey(retailer="tesco", name="Anything", gtin=None)
        result = resolver.resolve(key)
        assert result.erp_sku == "VG-FALA-300"
        assert result.evidence is not None
        assert result.evidence.stratum == "custom"

    def test_append_handler_after_defaults(self) -> None:
        """A handler appended after defaults only fires when defaults miss."""
        products = _make_products()
        master = MasterIndex(products)

        fallback_called = []

        def fallback(
            ctx: ResolverContext, key: RetailerProductKey
        ) -> MappingResult | None:
            fallback_called.append(True)
            return None

        handlers = list(DEFAULT_HANDLERS) + [("fallback", fallback)]
        resolver = Resolver(master, handlers=handlers)

        key = RetailerProductKey(
            retailer="tesco", name="does not exist anywhere", gtin=None
        )
        result = resolver.resolve(key)
        assert result.state == "Unmapped"
        assert len(fallback_called) == 1

    def test_e1_gtin_hit_skips_later_handlers(self) -> None:
        products = _make_products()
        master = MasterIndex(products)

        later_called = []

        def spy(ctx: ResolverContext, key: RetailerProductKey) -> MappingResult | None:
            later_called.append(True)
            return None

        handlers = list(DEFAULT_HANDLERS) + [("spy", spy)]
        resolver = Resolver(master, handlers=handlers)

        key = RetailerProductKey(
            retailer="tesco", name="whatever", gtin="5000001"
        )
        result = resolver.resolve(key)
        assert result.erp_sku == "VG-FALA-300"
        assert result.evidence is not None
        assert result.evidence.stratum == "gtin_current"
        assert len(later_called) == 0

    def test_resolver_context_exposes_config(self) -> None:
        products = _make_products()
        master = MasterIndex(products)

        resolver = Resolver(
            master,
            auto_threshold=0.75,
            e4_min_score=0.10,
        )
        assert resolver.context.auto_threshold == 0.75
        assert resolver.context.e4_min_score == 0.10
