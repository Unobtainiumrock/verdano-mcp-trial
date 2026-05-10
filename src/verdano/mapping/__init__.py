"""Bipartite mapping resolver — Fellegi-Sunter cascade.

Per D-011 + formalism §3:
    gtin_current   →  w = (1-ε)/K_x
    gtin_legacy    →  w = (1-γ)(1-ε)/K_x
    alias_exact    →  w = (1-ε)/K_x^α
    tfidf_overlap  →  w = tfidf·(1-ε)/K_x^α
    fuzzy_jw       →  w = JW(name)²

The cascade governs *discovery order* (gtin_current preempts gtin_legacy
preempts ... preempts fuzzy_jw). Scores are independent of stratum-of-origin
once the resolver fires.
"""

from verdano.mapping.priors import CalibrationPriors
from verdano.mapping.resolver import MasterIndex, Resolver

__all__ = ["CalibrationPriors", "MasterIndex", "Resolver"]
