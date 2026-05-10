"""Bipartite mapping resolver — Fellegi-Sunter cascade.

Per D-011 + formalism §3:
    E_1 (current_gtins)  →  w_1 = (1-ε)/K_x
    E_2 (legacy_gtins)   →  w_2 = (1-γ)(1-ε)/K_x
    E_3 (aliases)        →  w_3 = (1-ε)/K_x^α
    E_4 (fuzzy name)     →  w_4 = JW(name)²

The cascade governs *discovery order* (E_1 preempts E_2 preempts ... preempts
E_4). Scores are independent of stratum-of-origin once the resolver fires.
"""

from verdano.mapping.priors import CalibrationPriors
from verdano.mapping.resolver import MasterIndex, Resolver

__all__ = ["CalibrationPriors", "MasterIndex", "Resolver"]
