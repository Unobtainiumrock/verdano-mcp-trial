"""TF-IDF token-overlap scorer over the ERP master vocabulary.

Per D-011 + Gemini iteration 5 option 1: score retailer-side strings against
ERP product vocabularies using IDF-weighted token overlap. A match on a rare
token (e.g., "falafel") carries more signal than a match on a common one
(e.g., "400g", "soup"). Locked as stratum **E3b** under **D-013**.

Scoring formula (Gemini iteration 5):

    score(s, P) = (Σ IDF(t) for t in tokens(s) ∩ vocab(P)) / (Σ IDF(t) for t in tokens(s))

Score is in `[0, 1]`. Interpret as: the fraction of the retailer string's
information content that this ERP product's vocabulary supports.

Asymmetric: a single rare token in s matched against any product containing
that token gives a high score. The cascade compensates: E3b only fires when
exact alias (E3) misses, and below E3b is JW² (E4) which is much stricter on
short strings.
"""

from __future__ import annotations

import math
from collections import defaultdict

from verdano.erp.models import Product
from verdano.mapping.normalize import normalize, tokens


class TfIdfIndex:
    """Pre-computed IDF over the ERP master, with a per-product vocabulary.

    Built once at MasterIndex construction time. Per-string scoring is then
    O(|tokens(s)| × |products|) — small at trial scale (12 products × ~5
    tokens). Scales to thousands of products via simple inverted-index
    optimizations not built here (deferred).
    """

    def __init__(self, products: list[Product]) -> None:
        # Per-product vocabulary set (deduplicated tokens from name + aliases).
        self._vocab: dict[str, frozenset[str]] = {}
        # Document frequency: how many products contain each token.
        doc_freq: dict[str, int] = defaultdict(int)

        for p in products:
            seen: set[str] = set()
            seen.update(tokens(normalize(p.name)))
            for alias in p.aliases:
                seen.update(tokens(normalize(alias)))
            self._vocab[p.sku] = frozenset(seen)
            for token in seen:
                doc_freq[token] += 1

        n = max(len(products), 1)
        # Smoothed IDF: log(N / (1 + df)) + 1, never zero or negative.
        # The +1 inside the denominator is standard sklearn-style smoothing
        # to avoid div-by-zero on unseen tokens; the +1 outside ensures
        # tokens in *every* product still carry some weight.
        self._idf: dict[str, float] = {
            t: math.log(n / (1 + df)) + 1.0 for t, df in doc_freq.items()
        }
        self._n = n

    def score(self, s: str, sku: str) -> float:
        """IDF-weighted fraction of `s` covered by SKU `sku`'s vocabulary.

        Returns 0.0 when:
          - `sku` is not in the master, or
          - `s` tokenizes to zero tokens (empty string).
        """
        vocab = self._vocab.get(sku)
        if vocab is None:
            return 0.0
        s_tokens = tokens(normalize(s))
        if not s_tokens:
            return 0.0
        # IDF for unseen tokens defaults to log(N / 1) + 1 = log(N) + 1
        # (same value as a token appearing in 0 products under our smoothing).
        # In practice, a retailer string token absent from the entire master
        # carries the maximum IDF, which is correct: it's maximally surprising.
        max_idf = math.log(self._n) + 1.0
        total = sum(self._idf.get(t, max_idf) for t in s_tokens)
        if total == 0:
            return 0.0
        matched = sum(self._idf.get(t, max_idf) for t in s_tokens if t in vocab)
        return matched / total

    def best_match(self, s: str) -> tuple[list[str], float]:
        """Return `(top_skus, top_score)`.

        `top_skus` is the *list* of SKUs sharing the highest score (ties
        preserved). At K_x > 1 the cascade collapses confidence via the
        Fellegi-Sunter ambiguity penalty (per D-011 §3.5.1).
        """
        if not self._vocab:
            return ([], 0.0)
        scores = {sku: self.score(s, sku) for sku in self._vocab}
        top_score = max(scores.values())
        if top_score <= 0.0:
            return ([], 0.0)
        # Stable sort so ties surface deterministically.
        top_skus = sorted(sku for sku, score in scores.items() if score == top_score)
        return (top_skus, top_score)

    @property
    def idf(self) -> dict[str, float]:
        """Read-only view of the IDF table — useful for debugging tests."""
        return dict(self._idf)
