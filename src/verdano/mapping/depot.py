"""Depot-string → ship_to resolver.

Maps retailer CSV location labels (e.g. "Daventry Chilled") to ERP
``ship_to`` customer IDs (e.g. "SHIP-TESCO-DAV").

Resolution cascade:
  1. Case-insensitive substring match on ``Customer.name``
  2. Fuzzy fallback via ``rapidfuzz.fuzz.partial_ratio``
  3. ``None`` if no confident match (caller falls back to explicit ID)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    from verdano.erp.models import Customer

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 75


def _normalize_for_compare(s: str) -> str:
    """Lowercase, strip non-alphanumeric (handles Sainsbury's vs sainsburys)."""
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").strip()


def resolve_depot(
    location_label: str,
    erp_customers: list[Customer],
    retailer: str,
) -> str | None:
    """Resolve a CSV location label to an ERP ``ship_to`` customer ID.

    Only considers ``ship_to`` customers whose name contains the retailer
    string (case-insensitive) to avoid cross-retailer false positives.

    Returns ``None`` when no confident match is found.
    """
    label_lower = location_label.lower().strip()
    if not label_lower:
        return None

    retailer_norm = _normalize_for_compare(retailer)
    candidates = [
        c for c in erp_customers
        if c.type == "ship_to" and retailer_norm in _normalize_for_compare(c.name)
    ]
    if not candidates:
        return None

    # Pass 1: exact substring (label appears inside Customer.name)
    substring_hits = [
        c for c in candidates
        if label_lower in c.name.lower()
    ]
    if len(substring_hits) == 1:
        return substring_hits[0].id

    # Pass 2: fuzzy match (best partial_ratio score)
    best_score = 0.0
    best_match: Customer | None = None
    for c in candidates:
        score = fuzz.partial_ratio(label_lower, c.name.lower())
        if score > best_score:
            best_score = score
            best_match = c

    if best_match is not None and best_score >= FUZZY_THRESHOLD:
        logger.info(
            "depot fuzzy match: %r → %s (score=%.0f)",
            location_label, best_match.id, best_score,
        )
        return best_match.id

    logger.warning(
        "depot resolver: no confident match for %r among %s",
        location_label, [c.id for c in candidates],
    )
    return None
