"""Unsupervised calibration priors for the Fellegi-Sunter mapping resolver.

Per D-011, default initial values are starting points for the trial. Once
labeled review-resolution data accumulates (~200 entries), all three become
learnable from the supervised stream.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CalibrationPriors(BaseModel):
    """Three unsupervised priors driving the Fellegi-Sunter posteriors.

    `epsilon`: P(retailer string is fundamentally wrong despite matching).
    `gamma`:   P(legacy GTIN points to a superseded SKU).
    `alpha`:   alias-collision dampening exponent in the denominator.

    Default values per Gemini iteration 8 worked example.
    """

    model_config = ConfigDict(frozen=True)

    epsilon: float = Field(default=0.02, ge=0.0, le=1.0)
    gamma: float = Field(default=0.10, ge=0.0, le=1.0)
    alpha: float = Field(default=1.5, gt=0.0)


DEFAULT_PRIORS = CalibrationPriors()
