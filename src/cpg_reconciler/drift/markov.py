"""Markov regime-detection drift strategy (D-024).

Detects systematic forecast drift by modelling per-SKU residual histories
as a discrete-state Markov chain. The ``TransitionMatrix`` captures the
empirical transition probabilities between residual states (accurate,
over_forecast, under_forecast). The ``markov_strategy`` function checks
for:

1. **Persistence**: a SKU stuck in a non-accurate state for >= k weeks.
2. **Divergence**: a SKU whose transition profile differs from the
   population-level matrix.

Requires multi-week residual history accumulated via ``Repository``.
The strategy degrades gracefully when history is insufficient.

Architecture: uses **Option C** (MarkovDriftContext subclass) so
``DriftContext`` stays clean and future strategies define their own
context subclasses following the same pattern.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field as dataclass_field

from cpg_reconciler.drift.baseline import (
    DEFAULT_STRATEGIES,
    DriftContext,
    DriftReport,
    register_drift_class,
)
from cpg_reconciler.drift.types import (
    DriftDirection,
    DriftSignal,
    register_drift_direction,
)
from cpg_reconciler.storage.repository import ResidualRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MARKOV_STATES: tuple[str, ...] = ("accurate", "over_forecast", "under_forecast")


# ---------------------------------------------------------------------------
# MarkovDriftContext — Option C context subclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkovDriftContext(DriftContext):
    """Extended context carrying multi-week residual history for Markov.

    Inherits all ``DriftContext`` fields. The pipeline constructs this
    when ``mode="markov"`` by loading history from the Repository.
    """

    residual_history: dict[str, list[ResidualRecord]] = dataclass_field(default_factory=dict)
    min_weeks: int = 4
    persistence_threshold: int = 3
    max_history_weeks: int = 52
    kl_divergence_threshold: float = 0.5


# ---------------------------------------------------------------------------
# TransitionMatrix — pure math, no I/O
# ---------------------------------------------------------------------------


class TransitionMatrix:
    """Empirical Markov transition matrix with Laplace smoothing.

    The matrix is parameterised by a tuple of state names and a smoothing
    constant (default 1.0 = add-one / Laplace). It supports both batch
    construction via ``from_history`` and incremental streaming via
    ``update_transition``.
    """

    def __init__(
        self,
        states: tuple[str, ...] = MARKOV_STATES,
        smoothing: float = 1.0,
    ) -> None:
        self._states = states
        self._smoothing = smoothing
        self._state_idx = {s: i for i, s in enumerate(states)}
        n = len(states)
        self._counts: list[list[int]] = [[0] * n for _ in range(n)]

    @classmethod
    def from_history(
        cls,
        records: list[ResidualRecord],
        states: tuple[str, ...] = MARKOV_STATES,
        smoothing: float = 1.0,
    ) -> TransitionMatrix:
        """Build a transition matrix from an ordered residual history."""
        mat = cls(states=states, smoothing=smoothing)
        for prev, curr in zip(records, records[1:]):
            if prev.direction in mat._state_idx and curr.direction in mat._state_idx:
                mat.update_transition(prev.direction, curr.direction)
        return mat

    def update_transition(self, from_state: str, to_state: str) -> None:
        """Increment the (from, to) transition count."""
        i = self._state_idx[from_state]
        j = self._state_idx[to_state]
        self._counts[i][j] += 1

    @property
    def total_transitions(self) -> int:
        return sum(c for row in self._counts for c in row)

    def probability(self, from_state: str, to_state: str) -> float:
        """Laplace-smoothed transition probability P(to | from)."""
        i = self._state_idx[from_state]
        j = self._state_idx[to_state]
        row_total = sum(self._counts[i])
        return (self._counts[i][j] + self._smoothing) / (
            row_total + self._smoothing * len(self._states)
        )

    def row_probabilities(self, from_state: str) -> dict[str, float]:
        """Full probability distribution for transitions from ``from_state``."""
        return {s: self.probability(from_state, s) for s in self._states}

    def persistence_prob(self, state: str, k: int) -> float:
        """P(staying in ``state`` for ``k`` consecutive steps) = p_ss^k."""
        p_ss = self.probability(state, state)
        return p_ss ** k

    def stationary_distribution(self) -> dict[str, float]:
        """Compute the stationary distribution via power iteration.

        Falls back to uniform if the matrix is degenerate (all zeros
        before smoothing, which can't happen with Laplace > 0, but
        defended against for robustness).
        """
        n = len(self._states)
        pi = [1.0 / n] * n

        for _ in range(200):
            new_pi = [0.0] * n
            for j in range(n):
                for i in range(n):
                    new_pi[j] += pi[i] * self.probability(self._states[i], self._states[j])
            total = sum(new_pi)
            if total > 0:
                new_pi = [p / total for p in new_pi]
            converged = all(abs(new_pi[i] - pi[i]) < 1e-10 for i in range(n))
            pi = new_pi
            if converged:
                break

        return {self._states[i]: pi[i] for i in range(n)}


# ---------------------------------------------------------------------------
# Register Markov-specific directions and drift classes
# ---------------------------------------------------------------------------

for _d in ("persistent_over", "persistent_under", "regime_drift", "stable",
           "skipped_insufficient_data"):
    register_drift_direction(_d)

for _dc in ("persistent_over", "persistent_under", "regime_drift", "stable",
            "skipped_insufficient_data"):
    register_drift_class(_dc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _consecutive_tail_count(records: list[ResidualRecord]) -> tuple[str, int]:
    """Count how many consecutive weeks at the tail share the same direction.

    Returns (direction, count). If records is empty, returns ("", 0).
    """
    if not records:
        return ("", 0)
    tail_dir = records[-1].direction
    count = 0
    for rec in reversed(records):
        if rec.direction == tail_dir:
            count += 1
        else:
            break
    return (tail_dir, count)


def _kl_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """KL divergence D_KL(p || q) between two discrete distributions.

    Both distributions are clamped to a floor of 1e-10 to avoid log(0).
    Returns 0.0 when p == q.
    """
    total = 0.0
    for key in p:
        pi = max(p.get(key, 0.0), 1e-10)
        qi = max(q.get(key, 0.0), 1e-10)
        total += pi * math.log(pi / qi)
    return total


# ---------------------------------------------------------------------------
# markov_strategy — the strategy function
# ---------------------------------------------------------------------------


def markov_strategy(ctx: DriftContext) -> DriftReport:
    """Markov regime-detection over multi-week residual histories.

    Requires a ``MarkovDriftContext`` (Option C). If the context is a
    plain ``DriftContext``, returns an empty report with a reason.

    For each SKU with sufficient history (>= ``min_weeks``):
    1. Build a per-SKU ``TransitionMatrix``.
    2. Check persistence: consecutive weeks in the same non-accurate state.
    3. Check divergence: compare per-SKU transitions vs population matrix.

    SKUs with insufficient history are reported as ``skipped_insufficient_data``.
    """
    if not isinstance(ctx, MarkovDriftContext):
        return DriftReport(
            mode="markov",
            iso_week_forecast=ctx.iso_week_forecast,
            iso_week_actuals=ctx.iso_week_actuals,
            summary={"skipped_insufficient_data": 0},
            signals=[],
        )

    history = ctx.residual_history
    signals: list[DriftSignal] = []
    skipped_unmapped = 0

    population_matrix = TransitionMatrix(states=MARKOV_STATES)
    sku_matrices: dict[str, TransitionMatrix] = {}

    for sku, records in history.items():
        if len(records) < ctx.min_weeks:
            continue
        mat = TransitionMatrix.from_history(records)
        sku_matrices[sku] = mat
        for prev, curr in zip(records, records[1:]):
            if prev.direction in population_matrix._state_idx and curr.direction in population_matrix._state_idx:
                population_matrix.update_transition(prev.direction, curr.direction)

    pop_stationary = population_matrix.stationary_distribution()

    for fc in ctx.forecast_lines:
        mapping = ctx.mappings_by_key.get(fc.retailer_key.model_dump_json())
        if mapping is None or mapping.state != "Resolved" or mapping.erp_sku is None:
            skipped_unmapped += 1
            continue

        sku = mapping.erp_sku
        records = history.get(sku, [])

        if len(records) < ctx.min_weeks:
            signals.append(DriftSignal(
                mode="markov",
                retailer=fc.retailer,
                iso_week_forecast=ctx.iso_week_forecast,
                iso_week_actuals=ctx.iso_week_actuals,
                erp_sku=sku,
                retailer_key=fc.retailer_key,
                forecast_eaches=0,
                actuals_eaches=0,
                direction="skipped_insufficient_data",
                reason=(
                    f"only {len(records)} weeks of history for {sku}; "
                    f"need >= {ctx.min_weeks} for Markov analysis"
                ),
            ))
            continue

        mat = sku_matrices[sku]
        tail_dir, tail_count = _consecutive_tail_count(records)

        direction: DriftDirection
        reason: str
        p_persist = mat.persistence_prob(tail_dir, tail_count) if tail_count > 0 else 1.0

        if tail_dir != "accurate" and tail_count >= ctx.persistence_threshold:
            dir_short = tail_dir.replace("_forecast", "")
            direction = f"persistent_{dir_short}"
            reason = (
                f"{sku} has been {tail_dir} for {tail_count} consecutive weeks; "
                f"P(persist)={p_persist:.3f}. "
                f"Transition row: {mat.row_probabilities(tail_dir)}"
            )
        else:
            sku_stationary = mat.stationary_distribution()
            divergence = _kl_divergence(sku_stationary, pop_stationary)
            if divergence > ctx.kl_divergence_threshold:
                direction = "regime_drift"
                reason = (
                    f"{sku} stationary dist {sku_stationary} diverges from "
                    f"population {pop_stationary}; KL={divergence:.3f}"
                )
            else:
                direction = "stable"
                reason = (
                    f"{sku} tail state '{tail_dir}' for {tail_count} week(s); "
                    f"within normal transition profile. KL={divergence:.3f}"
                )

        signals.append(DriftSignal(
            mode="markov",
            retailer=fc.retailer,
            iso_week_forecast=ctx.iso_week_forecast,
            iso_week_actuals=ctx.iso_week_actuals,
            erp_sku=sku,
            retailer_key=fc.retailer_key,
            forecast_eaches=0,
            actuals_eaches=0,
            direction=direction,
            persistence_weeks=tail_count,
            transition_probability=p_persist,
            reason=reason,
        ))

    counts: Counter[str] = Counter(s.direction for s in signals)
    summary: dict[str, int] = {
        "persistent_over": counts.get("persistent_over", 0),
        "persistent_under": counts.get("persistent_under", 0),
        "regime_drift": counts.get("regime_drift", 0),
        "stable": counts.get("stable", 0),
        "skipped_insufficient_data": counts.get("skipped_insufficient_data", 0),
        "skipped_unmapped": skipped_unmapped,
    }
    return DriftReport(
        mode="markov",
        iso_week_forecast=ctx.iso_week_forecast,
        iso_week_actuals=ctx.iso_week_actuals,
        summary=summary,
        signals=signals,
    )


# ---------------------------------------------------------------------------
# Register into the default strategy map
# ---------------------------------------------------------------------------

DEFAULT_STRATEGIES["markov"] = markov_strategy
