"""Cascade resolver: retailer key → ERP sku, with provenance and confidence.

The `MasterIndex` pre-computes the Fellegi-Sunter collision dictionary K_x for
every key class (current_gtins, legacy_gtins, aliases, names) at construction
time. The `Resolver` walks an ordered chain of `StratumHandler` functions,
returning the first `MappingResult` produced. New strata (e.g.
`llm_augmented`) are added by appending a handler — no if/elif surgery
required.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from rapidfuzz.distance import JaroWinkler

from verdano.canonical import (
    MappingEvidence,
    MappingResult,
    MappingState,
    RetailerProductKey,
    Stratum,
)
from verdano.erp.models import Product
from verdano.mapping.normalize import normalize as _norm, tokens as _tokens
from verdano.mapping.priors import DEFAULT_PRIORS, CalibrationPriors
from verdano.mapping.tfidf import TfIdfIndex

StratumHandler = Callable[["ResolverContext", RetailerProductKey], MappingResult | None]
"""Signature for cascade stratum handlers.

A handler receives the shared context (index, priors, thresholds) and a key.
Return a `MappingResult` to short-circuit the cascade, or `None` to pass.
"""


class ResolverContext:
    """Shared state passed to each stratum handler."""

    def __init__(
        self,
        master: "MasterIndex",
        priors: CalibrationPriors,
        auto_threshold: float,
        tfidf_min_score: float,
        tfidf_min_matched_tokens: int,
        e4_min_score: float,
    ) -> None:
        self.master = master
        self.priors = priors
        self.auto_threshold = auto_threshold
        self.tfidf_min_score = tfidf_min_score
        self.tfidf_min_matched_tokens = tfidf_min_matched_tokens
        self.e4_min_score = e4_min_score

    def build_result(
        self,
        key: RetailerProductKey,
        sku: str,
        score: float,
        stratum: Stratum,
        matched_value: str,
        k_x: int,
    ) -> MappingResult:
        confidence = max(0.0, min(1.0, score))
        state: MappingState = (
            "Resolved" if confidence >= self.auto_threshold else "NeedsVerification"
        )
        return MappingResult(
            retailer_key=key,
            erp_sku=sku,
            confidence=confidence,
            state=state,
            evidence=MappingEvidence(
                stratum=stratum,
                matched_value=matched_value,
                collision_count=k_x,
            ),
        )


# ---------------------------------------------------------------------------
# Built-in stratum handlers
# ---------------------------------------------------------------------------


def _handle_gtin_current(ctx: ResolverContext, key: RetailerProductKey) -> MappingResult | None:
    """Current GTIN exact match."""
    if not key.gtin:
        return None
    candidates = ctx.master.lookup_current_gtin(key.gtin)
    if not candidates:
        return None
    k_x = len(candidates)
    w = (1 - ctx.priors.epsilon) / k_x
    return ctx.build_result(key, candidates[0], w, "gtin_current", key.gtin, k_x)


def _handle_gtin_legacy(ctx: ResolverContext, key: RetailerProductKey) -> MappingResult | None:
    """Legacy GTIN exact match."""
    if not key.gtin:
        return None
    candidates = ctx.master.lookup_legacy_gtin(key.gtin)
    if not candidates:
        return None
    k_x = len(candidates)
    w = (1 - ctx.priors.gamma) * (1 - ctx.priors.epsilon) / k_x
    return ctx.build_result(key, candidates[0], w, "gtin_legacy", key.gtin, k_x)


def _handle_alias_exact(ctx: ResolverContext, key: RetailerProductKey) -> MappingResult | None:
    """Alias / canonical-name exact match."""
    candidates = ctx.master.lookup_alias(key.name)
    if not candidates:
        return None
    k_x = len(candidates)
    w = (1 - ctx.priors.epsilon) / (k_x ** ctx.priors.alpha)
    return ctx.build_result(key, candidates[0], w, "alias_exact", key.name, k_x)


def _count_matched_tokens(
    master: "MasterIndex", retailer_name: str, sku: str
) -> int:
    """How many retailer tokens appear in the product's vocabulary?"""
    retailer_tokens = set(_tokens(_norm(retailer_name)))
    if not retailer_tokens:
        return 0
    product = master.products.get(sku)
    if product is None:
        return 0
    product_tokens = set(_tokens(_norm(product.name)))
    for alias in product.aliases:
        product_tokens.update(_tokens(_norm(alias)))
    return len(retailer_tokens & product_tokens)


def _handle_tfidf_overlap(ctx: ResolverContext, key: RetailerProductKey) -> MappingResult | None:
    """TF-IDF token-overlap (per D-013)."""
    tfidf_hit = ctx.master.tfidf_lookup(key.name, ctx.tfidf_min_score)
    if tfidf_hit is None:
        return None
    top_skus, top_score = tfidf_hit
    matched_count = _count_matched_tokens(ctx.master, key.name, top_skus[0])
    if matched_count < ctx.tfidf_min_matched_tokens:
        return None
    k_x = len(top_skus)
    w = top_score * (1 - ctx.priors.epsilon) / (k_x ** ctx.priors.alpha)
    return ctx.build_result(key, top_skus[0], w, "tfidf_overlap", key.name, k_x)


def _handle_fuzzy_jw(ctx: ResolverContext, key: RetailerProductKey) -> MappingResult | None:
    """Jaro-Winkler squared fuzzy match on canonical names."""
    fuzzy = ctx.master.fuzzy_search(key.name)
    if fuzzy is None:
        return None
    matched_name, sim = fuzzy
    w = sim ** 2
    if w < ctx.e4_min_score:
        return None
    candidates = ctx.master.skus_for_canonical_name(matched_name)
    if not candidates:
        return None
    k_x = len(candidates)
    return ctx.build_result(key, candidates[0], w, "fuzzy_jw", key.name, k_x)


DEFAULT_HANDLERS: list[tuple[str, StratumHandler]] = [
    ("gtin_current", _handle_gtin_current),
    ("gtin_legacy", _handle_gtin_legacy),
    ("alias_exact", _handle_alias_exact),
    ("tfidf_overlap", _handle_tfidf_overlap),
    ("fuzzy_jw", _handle_fuzzy_jw),
]


class MasterIndex:
    """Pre-computed lookup tables over the ERP product master.

    Indexes the master by every key class used in the cascade:
      - `by_current_gtin: dict[gtin, list[sku]]`
      - `by_legacy_gtin:  dict[gtin, list[sku]]`
      - `by_alias:        dict[norm(alias), list[sku]]`
      - `name_to_sku:     dict[norm(name), sku]`

    The Fellegi-Sunter collision count K_x for a matched value is the length
    of the corresponding list. The cascade resolver consults this index O(1)
    per stratum lookup.
    """

    def __init__(self, products: list[Product]) -> None:
        self._products = {p.sku: p for p in products}
        current_gtin_index: dict[str, set[str]] = defaultdict(set)
        legacy_gtin_index: dict[str, set[str]] = defaultdict(set)
        alias_index: dict[str, set[str]] = defaultdict(set)
        name_index: dict[str, set[str]] = defaultdict(set)

        for p in products:
            for g in p.current_gtins:
                current_gtin_index[g].add(p.sku)
            for g in p.legacy_gtins:
                legacy_gtin_index[g].add(p.sku)
            for a in p.aliases:
                alias_index[_norm(a)].add(p.sku)
            alias_index[_norm(p.name)].add(p.sku)
            name_index[_norm(p.name)].add(p.sku)

        self._by_current_gtin: dict[str, list[str]] = {
            k: sorted(v) for k, v in current_gtin_index.items()
        }
        self._by_legacy_gtin: dict[str, list[str]] = {
            k: sorted(v) for k, v in legacy_gtin_index.items()
        }
        self._by_alias: dict[str, list[str]] = {
            k: sorted(v) for k, v in alias_index.items()
        }

        self._name_index: dict[str, list[str]] = {
            k: sorted(v) for k, v in name_index.items()
        }

        self._tfidf = TfIdfIndex(products)

    @property
    def products(self) -> dict[str, Product]:
        return self._products

    @property
    def tfidf(self) -> TfIdfIndex:
        return self._tfidf

    def lookup_current_gtin(self, gtin: str) -> list[str]:
        return list(self._by_current_gtin.get(gtin, ()))

    def lookup_legacy_gtin(self, gtin: str) -> list[str]:
        return list(self._by_legacy_gtin.get(gtin, ()))

    def lookup_alias(self, name: str) -> list[str]:
        return list(self._by_alias.get(_norm(name), ()))

    def tfidf_lookup(self, name: str, min_score: float) -> tuple[list[str], float] | None:
        top_skus, top_score = self._tfidf.best_match(name)
        if not top_skus or top_score < min_score:
            return None
        return (top_skus, top_score)

    def fuzzy_search(self, name: str) -> tuple[str, float] | None:
        target = _norm(name)
        best_score = -1.0
        best_norm: str | None = None
        for n in self._name_index:
            sim = JaroWinkler.normalized_similarity(target, n)
            if sim > best_score:
                best_score = sim
                best_norm = n
        if best_norm is None:
            return None
        return best_norm, best_score

    def skus_for_canonical_name(self, normalized_name: str) -> list[str]:
        return list(self._name_index.get(normalized_name, ()))


class Resolver:
    """Walks an ordered chain of stratum handlers and returns the first hit.

    New strata (e.g. `llm_augmented`) can be appended to the handler list
    without modifying this class.
    """

    def __init__(
        self,
        master: MasterIndex,
        priors: CalibrationPriors = DEFAULT_PRIORS,
        auto_threshold: float = 0.90,
        tfidf_min_score: float = 0.5,
        tfidf_min_matched_tokens: int = 2,
        e4_min_score: float = 0.30,
        handlers: list[tuple[str, StratumHandler]] | None = None,
    ) -> None:
        self._ctx = ResolverContext(
            master=master,
            priors=priors,
            auto_threshold=auto_threshold,
            tfidf_min_score=tfidf_min_score,
            tfidf_min_matched_tokens=tfidf_min_matched_tokens,
            e4_min_score=e4_min_score,
        )
        self._handlers = handlers if handlers is not None else list(DEFAULT_HANDLERS)

    @property
    def context(self) -> ResolverContext:
        return self._ctx

    def resolve(self, key: RetailerProductKey) -> MappingResult:
        for _name, handler in self._handlers:
            result = handler(self._ctx, key)
            if result is not None:
                return result

        return MappingResult(
            retailer_key=key,
            erp_sku=None,
            confidence=0.0,
            state="Unmapped",
            evidence=None,
        )
