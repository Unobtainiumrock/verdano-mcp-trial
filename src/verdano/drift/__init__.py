"""Forecast-vs-actuals drift detection (D-012, D-020).

Supports multiple drift modes via a strategy pattern:

- **plausibility** (D-012): lagged-actuals ratio check. Compares a
  forward-week forecast against the prior week's EPOS actuals.
- **residual** (D-020): classical signed-residual check for same-period
  forecast vs actuals.

New strategies register without modifying existing code — see ``strategies.py``.
"""

from verdano.drift.baseline import (
    BaselineCompare,
    DriftAnalyzer,
    DriftContext,
    DriftReport,
    DriftStrategy,
    register_drift_class,
    plausibility_strategy,
)
from verdano.drift.strategies import residual_strategy
from verdano.drift.types import (
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
    "known_drift_directions",
    "plausibility_strategy",
    "register_drift_class",
    "register_drift_direction",
    "residual_strategy",
]
