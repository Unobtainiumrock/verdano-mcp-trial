"""Forecast-vs-actuals drift detection (D-012, D-020, D-024).

Supports multiple drift modes via a strategy pattern:

- **plausibility** (D-012): lagged-actuals ratio check. Compares a
  forward-week forecast against the prior week's EPOS actuals.
- **residual** (D-020): classical signed-residual check for same-period
  forecast vs actuals.
- **markov** (D-024): regime-detection via Markov transition-matrix
  analysis over multi-week residual histories.

New strategies register without modifying existing code — see ``strategies.py``
and ``markov.py``.
"""

from cpg_reconciler.drift.baseline import (
    BaselineCompare,
    DriftAnalyzer,
    DriftContext,
    DriftReport,
    DriftStrategy,
    register_drift_class,
    plausibility_strategy,
)
from cpg_reconciler.drift.markov import (
    MARKOV_STATES,
    MarkovDriftContext,
    TransitionMatrix,
    markov_strategy,
)
from cpg_reconciler.drift.strategies import residual_strategy
from cpg_reconciler.drift.types import (
    DriftSignal,
    register_drift_direction,
    known_drift_directions,
)

__all__ = [
    "BaselineCompare",
    "DriftAnalyzer",
    "DriftContext",
    "DriftReport",
    "DriftSignal",
    "DriftStrategy",
    "MARKOV_STATES",
    "MarkovDriftContext",
    "TransitionMatrix",
    "known_drift_directions",
    "markov_strategy",
    "plausibility_strategy",
    "register_drift_class",
    "register_drift_direction",
    "residual_strategy",
]
