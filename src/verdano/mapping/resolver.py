"""Cascade resolver: retailer key → ERP sku, with provenance and confidence.

The `MasterIndex` pre-computes the Fellegi-Sunter collision dictionary K_x for
every key class (current_gtins, legacy_gtins, aliases, names) at construction
time. The `Resolver` walks the cascade per retailer key, returning a
`MappingResult` with the chosen sku, calibrated confidence, and evidence.
"""

from __future__ import annotations

from collections import defaultdict

from rapidfuzz.distance import JaroWinkler

from verdano.canonical import (
    MappingEvidence,
    MappingResult,
    MappingState,
    RetailerProductKey,
    Stratum,
)
from verdano.erp.models import Product
from verdano.mapping.normalize import normalize as _norm
from verdano.mapping.priors import DEFAULT_PRIORS, CalibrationPriors
from verdano.mapping.tfidf import TfIdfIndex


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
        # Build per-key SKU sets first so we dedupe within-product. Multiple
        # paths from the *same* product to the same key (e.g., when D-013's
        # size normalizer collapses a name + an alias of the same SKU to the
        # same canonical string) must NOT inflate K_x at lookup time.
        current_gtin_index: dict[str, set[str]] = defaultdict(set)
        legacy_gtin_index: dict[str, set[str]] = defaultdict(set)
        alias_index: dict[str, set[str]] = defaultdict(set)
        self._name_index: dict[str, str] = {}

        for p in products:
            for g in p.current_gtins:
                current_gtin_index[g].add(p.sku)
            for g in p.legacy_gtins:
                legacy_gtin_index[g].add(p.sku)
            for a in p.aliases:
                alias_index[_norm(a)].add(p.sku)
            # Also index the canonical product name as an alias-strength match.
            alias_index[_norm(p.name)].add(p.sku)
            self._name_index[_norm(p.name)] = p.sku

        # Stable, deterministic ordering for downstream consumers (cascade picks
        # candidates[0] when K_x > 1; sorting makes the choice reproducible).
        self._by_current_gtin: dict[str, list[str]] = {
            k: sorted(v) for k, v in current_gtin_index.items()
        }
        self._by_legacy_gtin: dict[str, list[str]] = {
            k: sorted(v) for k, v in legacy_gtin_index.items()
        }
        self._by_alias: dict[str, list[str]] = {
            k: sorted(v) for k, v in alias_index.items()
        }

        self._tfidf = TfIdfIndex(products)

    @property
    def products(self) -> dict[str, Product]:
        return self._products

    @property
    def tfidf(self) -> TfIdfIndex:
        """The pre-computed TF-IDF scorer over the master vocabulary."""
        return self._tfidf

    def lookup_current_gtin(self, gtin: str) -> list[str]:
        return list(self._by_current_gtin.get(gtin, ()))

    def lookup_legacy_gtin(self, gtin: str) -> list[str]:
        return list(self._by_legacy_gtin.get(gtin, ()))

    def lookup_alias(self, name: str) -> list[str]:
        return list(self._by_alias.get(_norm(name), ()))

    def tfidf_lookup(self, name: str, min_score: float) -> tuple[list[str], float] | None:
        """Return `(top_skus, top_score)` from TF-IDF, or `None` if below threshold.

        Per D-013, E3b only fires when the IDF-weighted overlap exceeds
        `min_score` — otherwise we'd resolve via E3b for every retailer string
        that shares any token with any product. The threshold is the cascade's
        effective gate between "real partial match" and "give up, try fuzzy."
        """
        top_skus, top_score = self._tfidf.best_match(name)
        if not top_skus or top_score < min_score:
            return None
        return (top_skus, top_score)

    def fuzzy_search(self, name: str) -> tuple[str, float] | None:
        """Return the (best-matching name, similarity) over all canonical names.

        Uses normalized Jaro-Winkler. Returns `None` if no name in the master.
        """
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

    def sku_for_canonical_name(self, normalized_name: str) -> str:
        return self._name_index[normalized_name]


class Resolver:
    """Walks the discovery cascade and emits a calibrated `MappingResult`.

    The resolver does not enforce non-overlapping confidence bands (per D-011
    iteration 9). The cascade governs which generator fires first; the score
    on the resulting edge reflects only the per-stratum probability of
    correctness under the Fellegi-Sunter model (or JW² for fuzzy).

    `auto_threshold` is the global confidence threshold above which the result
    is `Resolved` (auto-allocate). Below it, `NeedsVerification` (operator
    review with a candidate). Per D-011, treat as provisional / operator-tunable
    until calibration data accumulates.
    """

    def __init__(
        self,
        master: MasterIndex,
        priors: CalibrationPriors = DEFAULT_PRIORS,
        auto_threshold: float = 0.90,
        tfidf_min_score: float = 0.5,
        tfidf_min_matched_tokens: int = 2,
        e4_min_score: float = 0.30,
    ) -> None:
        self._master = master
        self._priors = priors
        self._auto_threshold = auto_threshold
        self._tfidf_min_score = tfidf_min_score
        self._tfidf_min_matched_tokens = tfidf_min_matched_tokens
        self._e4_min_score = e4_min_score

    def resolve(self, key: RetailerProductKey) -> MappingResult:
        """Return the single best-edge mapping result for `key`.

        The cascade fires in order; the first stratum that produces *any*
        candidate determines the mapping. Lower strata are not consulted.
        Within a stratum, when multiple candidates exist (K_x > 1), the
        resolver returns the *first* candidate sku and the score reflects
        the ambiguity-density penalty — which usually drops the result into
        `NeedsVerification` automatically.
        """
        # E_1 — current GTIN.
        if key.gtin:
            candidates = self._master.lookup_current_gtin(key.gtin)
            if candidates:
                k_x = len(candidates)
                w = (1 - self._priors.epsilon) / k_x
                return self._build_result(
                    key, candidates[0], w, "E1", key.gtin, k_x
                )

        # E_2 — legacy GTIN.
        if key.gtin:
            candidates = self._master.lookup_legacy_gtin(key.gtin)
            if candidates:
                k_x = len(candidates)
                w = (1 - self._priors.gamma) * (1 - self._priors.epsilon) / k_x
                return self._build_result(
                    key, candidates[0], w, "E2", key.gtin, k_x
                )

        # E_3 — alias / canonical-name exact match.
        candidates = self._master.lookup_alias(key.name)
        if candidates:
            k_x = len(candidates)
            w = (1 - self._priors.epsilon) / (k_x ** self._priors.alpha)
            return self._build_result(key, candidates[0], w, "E3", key.name, k_x)

        # E_3b — TF-IDF token-overlap (per D-013). IDF-weighted partial match
        # when no exact alias hit. Catches retailer strings that share rare
        # tokens with an ERP product without exactly matching any alias.
        # Minimum-matching-tokens guard prevents single-rare-token false
        # positives like "VD" → VG-DAAL-400 at top_score=1.0.
        tfidf_hit = self._master.tfidf_lookup(key.name, self._tfidf_min_score)
        if tfidf_hit is not None:
            top_skus, top_score = tfidf_hit
            matched_count = self._count_matched_tokens(key.name, top_skus[0])
            if matched_count >= self._tfidf_min_matched_tokens:
                k_x = len(top_skus)
                # Confidence: IDF-overlap fraction × FS K_x penalty.
                w = top_score * (1 - self._priors.epsilon) / (k_x ** self._priors.alpha)
                return self._build_result(key, top_skus[0], w, "E3b", key.name, k_x)

        # E_4 — fuzzy match on canonical-name index. Minimum-score floor
        # prevents the cascade from emitting a misleading candidate when no
        # name in the master is even loosely similar to the retailer string.
        # Below the floor → return Unmapped so the operator sees "no candidate"
        # rather than "we guessed VG-DAAL but it's only 27% confident."
        fuzzy = self._master.fuzzy_search(key.name)
        if fuzzy is not None:
            matched_name, sim = fuzzy
            w = sim ** 2
            if w >= self._e4_min_score:
                sku = self._master.sku_for_canonical_name(matched_name)
                return self._build_result(key, sku, w, "E4", key.name, 1)

        # No match generated by any stratum.
        return MappingResult(
            retailer_key=key,
            erp_sku=None,
            confidence=0.0,
            state="Unmapped",
            evidence=None,
        )

    def _count_matched_tokens(self, retailer_name: str, sku: str) -> int:
        """How many of the retailer string's tokens appear in `sku`'s vocab?

        Used by the E3b minimum-matched-tokens guard to suppress single-rare-
        token auto-allocations (the asymmetric-IDF failure mode discussed in
        D-013's pushback section).
        """
        from verdano.mapping.normalize import normalize, tokens
        retailer_tokens = set(tokens(normalize(retailer_name)))
        if not retailer_tokens:
            return 0
        product = self._master.products.get(sku)
        if product is None:
            return 0
        product_tokens = set(tokens(normalize(product.name)))
        for alias in product.aliases:
            product_tokens.update(tokens(normalize(alias)))
        return len(retailer_tokens & product_tokens)

    def _build_result(
        self,
        key: RetailerProductKey,
        sku: str,
        score: float,
        stratum: Stratum,
        matched_value: str,
        k_x: int,
    ) -> MappingResult:
        # Note: per formalism §3.2, a cross-check between the matched ERP
        # product's temperature_band and any retailer-declared band would apply
        # a multiplicative penalty here. The trial fixture rows include
        # `temperature_band` on Sainsbury's forecast, but the canonical model
        # doesn't surface that field through to the resolver — the row context
        # is upstream at the pipeline layer. The hook is documented for
        # production scope and is not a blocker for the current cascade.
        confidence = max(0.0, min(1.0, score))
        state: MappingState = (
            "Resolved" if confidence >= self._auto_threshold else "NeedsVerification"
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
