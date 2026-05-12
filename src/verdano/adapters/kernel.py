"""DOW kernel learning strategies (D-009, D-021).

The ``KernelLearner`` protocol decouples DOW weight computation from the
static default profile. This lets the system evolve from the hardcoded
UK-grocery kernel to a learned per-retailer simplex-NNLS kernel once
multi-week EPOS data is available — without modifying the adapter, spec,
or disaggregation code.

Current implementation: ``StaticKernelLearner`` — returns a ``DOWKernel``
with the default UK-grocery weights unchanged.
Production upgrade at >= 4 weeks EPOS: ``NNLSKernelLearner`` — fits a
simplex-constrained NNLS model from historical daily sales patterns.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from verdano.adapters.spec import DEFAULT_DOW_KERNEL, DOW7, DOWKernel


@runtime_checkable
class KernelLearner(Protocol):
    """Compute or learn DOW disaggregation weights."""

    def learn(self, retailer_code: str) -> DOWKernel:
        """Return a ``DOWKernel`` for the given retailer.

        Parameters
        ----------
        retailer_code : str
            Registered retailer code (e.g., ``"tesco"``).

        Returns
        -------
        DOWKernel
            Frozen model with 7-tuple weights summing to 1.0.
        """
        ...


class StaticKernelLearner:
    """Return the built-in UK-grocery profile — no learning (D-009).

    This is the trial-scope default: when no EPOS history is available,
    every retailer gets ``DEFAULT_DOW_KERNEL``.
    """

    def __init__(self, default_weights: DOW7 = DEFAULT_DOW_KERNEL) -> None:
        self._default = DOWKernel(weights=default_weights)

    def learn(self, retailer_code: str) -> DOWKernel:
        return self._default


class NNLSKernelLearner:
    """Placeholder for simplex-NNLS learned kernel from EPOS data (D-009).

    Requires >= 4 weeks of daily EPOS data per retailer to fit. The
    resulting weights are constrained to the probability simplex
    (non-negative, sum-to-1) via projection after NNLS.

    Raises ``NotImplementedError`` until training data is available.
    """

    def __init__(self, min_weeks: int = 4) -> None:
        self._min_weeks = min_weeks

    def learn(self, retailer_code: str) -> DOWKernel:
        raise NotImplementedError(
            f"NNLSKernelLearner requires >= {self._min_weeks} weeks of "
            f"daily EPOS data for retailer {retailer_code!r}"
        )


DEFAULT_KERNEL_LEARNER: KernelLearner = StaticKernelLearner()
