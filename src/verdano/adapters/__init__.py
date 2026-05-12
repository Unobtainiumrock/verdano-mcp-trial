"""Config-driven retailer adapters (per D-001).

Per Gemini iteration 4 + our pushback: a single `Adapter` class parameterized
by a `RetailerSpec`. Onboarding retailer N+1 is a YAML/Pydantic spec, not a
new subclass. The morphism `Φ_r: P_CPG → P_normalized` (formalism §2) is the
adapter; its parameterization is the spec.
"""

from verdano.adapters.adapter import Adapter
from verdano.adapters.kernel import (
    DEFAULT_KERNEL_LEARNER,
    KernelLearner,
    NNLSKernelLearner,
    StaticKernelLearner,
)
from verdano.adapters.spec import (
    SAINSBURYS_SPEC,
    TESCO_SPEC,
    DOWKernel,
    RetailerSpec,
    UnitMode,
    get_spec,
)

__all__ = [
    "SAINSBURYS_SPEC",
    "TESCO_SPEC",
    "Adapter",
    "DEFAULT_KERNEL_LEARNER",
    "DOWKernel",
    "KernelLearner",
    "NNLSKernelLearner",
    "RetailerSpec",
    "StaticKernelLearner",
    "UnitMode",
    "get_spec",
]
