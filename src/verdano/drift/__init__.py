"""Forecast-vs-actuals plausibility check (trial-scope drift signal).

Per **D-012** + formalism §10: this is a *lagged-actuals plausibility check*,
not classical residual drift. We compare a forward-week forecast (e.g., W20)
against the prior week's EPOS actuals (e.g., W19) to flag implausible
deviations. Promo-flagged forecast lines are segmented out (uplift expected).

Classical drift detection requires forecast and actuals from the same period;
the trial fixture only provides forward forecasts and lagged actuals.
Markov-style true-drift modeling stays reserved per **D-006**.
"""

from verdano.drift.baseline import BaselineCompare, DriftReport
from verdano.drift.types import DriftSignal

__all__ = ["BaselineCompare", "DriftReport", "DriftSignal"]
