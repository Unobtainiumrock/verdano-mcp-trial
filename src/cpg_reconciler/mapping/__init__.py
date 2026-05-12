"""Bipartite mapping resolver — Fellegi-Sunter cascade.

Per D-011 + formalism §3:
    gtin_current   →  w = (1-ε)/K_x
    gtin_legacy    →  w = (1-γ)(1-ε)/K_x
    alias_exact    →  w = (1-ε)/K_x^α
    tfidf_overlap  →  w = tfidf·(1-ε)/K_x^α
    fuzzy_jw       →  w = JW(name)²

The cascade governs *discovery order* (gtin_current preempts gtin_legacy
preempts ... preempts fuzzy_jw). Raw scores are stratum-specific; the
pluggable ``Calibrator`` (D-021) transforms them into final confidence
values (default: clamp to [0, 1]). Post-calibration ``ConfidenceHook``
functions (D-022) apply contextual penalties (e.g., temperature-band
mismatch) before the auto/review threshold is evaluated.
"""

from cpg_reconciler.mapping.calibration import (
    Calibrator,
    DEFAULT_CALIBRATOR,
    SupervisedCalibrator,
    UnsupervisedCalibrator,
)
from cpg_reconciler.mapping.hooks import (
    ConfidenceHook,
    DEFAULT_HOOKS,
    temperature_band_penalty,
)
from cpg_reconciler.mapping.priors import CalibrationPriors
from cpg_reconciler.mapping.resolver import MasterIndex, Resolver

__all__ = [
    "Calibrator",
    "CalibrationPriors",
    "ConfidenceHook",
    "DEFAULT_CALIBRATOR",
    "DEFAULT_HOOKS",
    "MasterIndex",
    "Resolver",
    "SupervisedCalibrator",
    "UnsupervisedCalibrator",
    "temperature_band_penalty",
]
