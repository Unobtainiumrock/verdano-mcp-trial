"""String canonicalization for the cascade resolver.

Exposes a composable `NormalizationPipeline` of individual steps so callers
can extend normalization (e.g. brand-prefix stripping, stop-word removal)
without modifying this source.

The `DEFAULT_PIPELINE` replicates the original trial-scope normalizer
(lowercase → whitespace-collapse → size-unit conversion).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal

NormalizerStep = Callable[[str], str]

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|l)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Built-in normalizer steps
# ---------------------------------------------------------------------------


def lowercase(s: str) -> str:
    return s.lower()


def collapse_whitespace(s: str) -> str:
    return " ".join(s.split())


def normalize_sizes(s: str) -> str:
    """Convert kg→g and l→ml.  Operates on already-lowercased input."""

    def repl(match: re.Match[str]) -> str:
        value = Decimal(match.group(1))
        unit = match.group(2).lower()
        scaled = value * 1000
        new_unit = "g" if unit == "kg" else "ml"
        if scaled == scaled.to_integral_value():
            return f"{int(scaled)}{new_unit}"
        return f"{scaled.normalize()}{new_unit}"

    return _SIZE_RE.sub(repl, s)


def strip_brand_prefixes(prefixes: set[str]) -> NormalizerStep:
    """Return a step that strips known brand prefixes from the input."""
    sorted_prefixes = sorted(prefixes, key=len, reverse=True)

    def _step(s: str) -> str:
        for prefix in sorted_prefixes:
            if s.startswith(prefix):
                s = s[len(prefix) :].lstrip()
                break
        return s

    return _step


def remove_stop_words(stops: set[str]) -> NormalizerStep:
    """Return a step that removes stop words from the input."""

    def _step(s: str) -> str:
        return " ".join(w for w in s.split() if w not in stops)

    return _step


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class NormalizationPipeline:
    """Chain of `NormalizerStep` functions applied in order."""

    def __init__(self, steps: list[NormalizerStep]) -> None:
        self._steps = list(steps)

    def __call__(self, s: str) -> str:
        for step in self._steps:
            s = step(s)
        return s

    def with_step(self, step: NormalizerStep) -> "NormalizationPipeline":
        """Return a new pipeline with an additional step appended."""
        return NormalizationPipeline([*self._steps, step])


DEFAULT_PIPELINE = NormalizationPipeline([lowercase, collapse_whitespace, normalize_sizes])


# ---------------------------------------------------------------------------
# Backward-compatible API used by resolver, tfidf, and depot modules
# ---------------------------------------------------------------------------


def normalize(s: str) -> str:
    """Single canonical normalizer (delegates to DEFAULT_PIPELINE)."""
    return DEFAULT_PIPELINE(s)


def tokens(s: str) -> list[str]:
    """Tokenize a normalized string into space-separated components."""
    return s.split()
