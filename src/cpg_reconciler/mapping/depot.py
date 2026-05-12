"""Depot-string → ship_to resolver.

Maps retailer CSV location labels (e.g. "Daventry Chilled") to ERP
``ship_to`` customer IDs (e.g. "SHIP-TESCO-DAV").

Resolution cascade:
  1. Case-insensitive substring match on ``Customer.name``
  2. Fuzzy fallback via ``rapidfuzz.fuzz.partial_ratio``
  3. Optional LLM fallback (if an ``LLMClient`` is provided)
  4. ``None`` if no confident match (caller falls back to explicit ID)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

from cpg_reconciler.llm.client import strip_json_fences

if TYPE_CHECKING:
    from cpg_reconciler.erp.models import Customer
    from cpg_reconciler.llm.client import LLMClient

logger = logging.getLogger(__name__)

FUZZY_THRESHOLD = 75


def _normalize_for_compare(s: str) -> str:
    """Lowercase, strip non-alphanumeric (handles Sainsbury's vs sainsburys)."""
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").strip()


def resolve_depot(
    location_label: str,
    erp_customers: list["Customer"],
    retailer: str,
    *,
    fuzzy_threshold: int = FUZZY_THRESHOLD,
    llm_client: "LLMClient | None" = None,
    depot_llm_min_confidence: float = 0.50,
) -> str | None:
    """Resolve a CSV location label to an ERP ``ship_to`` customer ID.

    Only considers ``ship_to`` customers whose name contains the retailer
    string (case-insensitive) to avoid cross-retailer false positives.

    If ``llm_client`` is provided and the fuzzy match fails, asks the LLM
    to interpret the depot string as a final fallback.

    Returns ``None`` when no confident match is found.
    """
    label_norm = _normalize_for_compare(location_label)
    if not label_norm:
        return None

    retailer_norm = _normalize_for_compare(retailer)
    candidates = [
        c for c in erp_customers
        if c.type == "ship_to" and retailer_norm in _normalize_for_compare(c.name)
    ]
    if not candidates:
        return None

    # Pass 1: exact substring
    substring_hits = [
        c for c in candidates
        if label_norm in _normalize_for_compare(c.name)
    ]
    if len(substring_hits) == 1:
        return substring_hits[0].id

    # Pass 2: fuzzy match
    best_score = 0.0
    best_match: "Customer | None" = None
    for c in candidates:
        score = fuzz.partial_ratio(label_norm, _normalize_for_compare(c.name))
        if score > best_score:
            best_score = score
            best_match = c

    if best_match is not None and best_score >= fuzzy_threshold:
        logger.info(
            "depot fuzzy match: %r → %s (score=%.0f)",
            location_label, best_match.id, best_score,
        )
        return best_match.id

    # Pass 3: LLM fallback
    if llm_client is not None:
        result = _llm_depot_fallback(
            llm_client, location_label, candidates,
            min_confidence=depot_llm_min_confidence,
        )
        if result is not None:
            return result

    logger.warning(
        "depot resolver: no confident match for %r among %s",
        location_label, [c.id for c in candidates],
    )
    return None


def _llm_depot_fallback(
    client: "LLMClient",
    location_label: str,
    candidates: list["Customer"],
    *,
    min_confidence: float = 0.50,
) -> str | None:
    """Ask the LLM to pick the best depot match from the candidate list."""
    cand_lines = "\n".join(f"  - {c.id}: {c.name}" for c in candidates)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a UK grocery logistics expert. "
                "Given a retailer depot/location label and ERP ship-to customers, "
                "select the best match. Reply ONLY with JSON: "
                '{"id": "<customer_id_or_null>", "confidence": <0.0-1.0>}'
            ),
        },
        {
            "role": "user",
            "content": (
                f'Location label: "{location_label}"\n\n'
                f"Ship-to candidates:\n{cand_lines}\n\n"
                "Which candidate best matches the location label?"
            ),
        },
    ]

    try:
        raw = client.complete(messages, temperature=0.0)
        parsed = json.loads(strip_json_fences(raw))
    except Exception:
        logger.warning("LLM depot fallback failed for %r", location_label, exc_info=True)
        return None

    chosen_id: str | None = parsed.get("id")
    conf: float = float(parsed.get("confidence", 0.0))

    if not chosen_id or conf < min_confidence:
        return None

    valid_ids = {c.id for c in candidates}
    if chosen_id not in valid_ids:
        return None

    logger.info(
        "depot LLM fallback: %r → %s (confidence=%.2f)",
        location_label, chosen_id, conf,
    )
    return chosen_id
