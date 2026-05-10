"""String canonicalization for the cascade resolver.

Two passes, applied symmetrically to both the ERP-master alias index keys
and the retailer-side lookup strings:

  1. Lowercase + whitespace-collapse — undoes case and spacing chaos.
  2. Size-unit normalization — `0.5kg → 500g`, `2L → 2000ml`. Pure regex,
     no labels required, idempotent. Closes the deliberate fixture gotcha
     "Tom Basil Soup 0.5kg" ↔ "Tomato Soup 500g" (the lexical-canonicalization
     half; the alias half is already in the ERP master).

Locked under D-013 as the trial-scope canonicalization. More aggressive moves
(brand-prefix stripping, stop-word removal, plural↔singular) are deferred —
they introduce ambiguity at small data scale and the master's curated alias
list already covers the cases that would matter.
"""

from __future__ import annotations

import re
from decimal import Decimal

# Match a number (optional decimal) followed by a kg/l unit at a word boundary.
# Examples that match: "0.5kg", "1.5 kg", "2L", "0.25kg".
# Examples that do not: "100ml" (l is not preceded by a digit-then-optional-space),
# "1lb" (\b fails — "b" is a word char), "kgallon" (no leading digit).
_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|l)\b", re.IGNORECASE)


def _normalize_sizes(s: str) -> str:
    """Convert kg→g and l→ml in-place. Operates on lowercased input.

    Examples:
      `_normalize_sizes("0.5kg")`        → `"500g"`
      `_normalize_sizes("1.5kg")`        → `"1500g"`
      `_normalize_sizes("2l")`           → `"2000ml"`
      `_normalize_sizes("tom soup 0.5kg")` → `"tom soup 500g"`
      `_normalize_sizes("500g")`         → `"500g"`   (no kg/l → no-op)
      `_normalize_sizes("100ml")`        → `"100ml"`  (no leading digit-space-then-l)
    """

    def repl(match: re.Match[str]) -> str:
        value = Decimal(match.group(1))
        unit = match.group(2).lower()
        scaled = value * 1000
        new_unit = "g" if unit == "kg" else "ml"
        # Emit clean integer when the scaled value is whole; otherwise let
        # Decimal handle the formatting (still rare for CPG sizes).
        if scaled == scaled.to_integral_value():
            return f"{int(scaled)}{new_unit}"
        return f"{scaled.normalize()}{new_unit}"

    return _SIZE_RE.sub(repl, s)


def normalize(s: str) -> str:
    """The single canonical normalizer for the cascade resolver.

    Order matters: lowercase first so the size-unit regex can do
    case-insensitive matching cheaply.
    """
    return _normalize_sizes(" ".join(s.lower().split()))


def tokens(s: str) -> list[str]:
    """Tokenize a normalized string into its space-separated components.

    Used by the TF-IDF scorer (E3b stratum). Does not deduplicate — repeated
    tokens contribute repeated mass to the IDF sum. For the trial fixtures
    this never happens; documented for completeness.
    """
    return s.split()
