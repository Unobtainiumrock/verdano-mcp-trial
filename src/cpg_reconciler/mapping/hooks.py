"""Post-calibration confidence hooks (D-022).

Hooks apply multiplicative penalties to the calibrated confidence *after*
the ``Calibrator`` has run but *before* the auto/review threshold is
evaluated. This separation keeps calibration pure (score -> probability)
while allowing contextual red-flag checks to suppress confidence.

Per formalism section 3.2:
    w(e) <- lambda * w(e)
where lambda in (0, 1] is the penalty factor.

Hooks are composable: multiple hooks multiply together. A hook that has
no opinion returns 1.0 (identity under multiplication).
"""

from __future__ import annotations

from collections.abc import Callable

from cpg_reconciler.erp.models import Product

ConfidenceHook = Callable[[float, str, dict[str, Product]], float]
"""Signature for post-calibration confidence hooks.

Parameters
----------
confidence : float
    Calibrated confidence from the Calibrator, in [0, 1].
sku : str
    The matched ERP SKU.
products : dict[str, Product]
    The full product master, keyed by SKU.

Returns
-------
float
    Adjusted confidence in [0, 1]. Return ``confidence`` unchanged
    (or 1.0 as a multiplicative identity) to express no opinion.
"""


def temperature_band_penalty(
    lambda_penalty: float = 0.3,
) -> ConfidenceHook:
    """Penalize matches where the retailer name suggests a different band.

    Checks whether temperature-band keywords in the retailer-side product
    name conflict with the matched ERP product's ``temperature_band``.
    A chilled-keyword name matched to an ambient product (or vice versa)
    is a high-precision "mapping wrong" signal (fixture gotcha #4).

    The penalty is multiplicative: ``confidence *= lambda_penalty`` when
    a mismatch is detected. The default ``lambda_penalty=0.3`` is
    aggressive enough to push most matches below the 0.90 auto-threshold,
    forcing human review without outright rejecting the match.
    """
    _BAND_KEYWORDS: dict[str, set[str]] = {
        "chilled": {"chilled", "fresh", "refrigerated", "cold"},
        "frozen": {"frozen", "freeze", "ice"},
        "ambient": {"ambient", "shelf", "dry", "long life", "longlife"},
    }

    def _hook(confidence: float, sku: str, products: dict[str, Product]) -> float:
        product = products.get(sku)
        if product is None:
            return confidence

        name_lower = product.name.lower()
        product_band = product.temperature_band

        for band, keywords in _BAND_KEYWORDS.items():
            if band == product_band:
                continue
            if any(kw in name_lower for kw in keywords):
                return confidence * lambda_penalty

        return confidence

    return _hook


DEFAULT_HOOKS: list[ConfidenceHook] = []
"""No hooks active by default — preserves exact pre-D-022 behavior."""
