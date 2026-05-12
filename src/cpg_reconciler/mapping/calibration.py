"""Confidence calibration strategies for the mapping resolver (D-011, D-021).

The ``Calibrator`` protocol decouples the raw matching score from the
calibrated confidence probability. This lets the system evolve from the
current unsupervised Fellegi-Sunter posteriors to a supervised calibrator
(Cascaded Classification LR, isotonic regression) without modifying the
resolver or handler chain.

Current implementation: ``UnsupervisedCalibrator`` — clamp-to-[0,1].
Production upgrade at >=200 labels: ``SupervisedCalibrator`` — fit from
labeled review-resolution data.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from cpg_reconciler.canonical import Stratum


@runtime_checkable
class Calibrator(Protocol):
    """Transform a raw stratum score into a calibrated confidence [0, 1]."""

    def calibrate(self, score: float, stratum: Stratum, k_x: int) -> float:
        """Return a calibrated probability in [0, 1].

        Parameters
        ----------
        score : float
            Raw score from the stratum handler (Fellegi-Sunter posterior,
            JW², TF-IDF overlap, etc.).
        stratum : Stratum
            Which stratum produced the score — supervised models use this
            as a categorical feature.
        k_x : int
            Collision count for the matched value — how many SKUs share it.
        """
        ...


class UnsupervisedCalibrator:
    """Clamp raw score to [0, 1] — the trial-scope default (D-011).

    The Fellegi-Sunter posterior and JW² scores are already designed to be
    in [0, 1], so clamping preserves them for well-behaved inputs. For
    out-of-range values (possible with custom handlers) it saturates.
    """

    def calibrate(self, score: float, stratum: Stratum, k_x: int) -> float:
        return max(0.0, min(1.0, score))


class SupervisedCalibrator:
    """Placeholder for Cascaded Classification LR calibrator (D-011).

    Requires >= 200 labeled review-resolution entries. The production
    implementation will extend the ``Calibrator`` protocol with a
    ``fit(labels)`` method and use ``(score, stratum, k_x)`` plus
    additional features derived from the resolver context. Isotonic
    regression replaces LR at >= 1000 labels.

    Raises ``NotImplementedError`` until a trained model is loaded.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path

    def calibrate(self, score: float, stratum: Stratum, k_x: int) -> float:
        raise NotImplementedError(
            "SupervisedCalibrator requires a trained model; "
            "provide model_path or train with >= 200 labeled examples first"
        )


DEFAULT_CALIBRATOR: Calibrator = UnsupervisedCalibrator()
