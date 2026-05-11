"""Post-cascade LLM re-ranker (D-019).

Runs *after* the deterministic cascade resolves a mapping. Selectively
sends low-confidence or ambiguous matches to the LLM for validation,
catching false positives from stale aliases or weak fuzzy hits without
burning API calls on high-confidence GTIN matches.

The re-ranker is a no-op when no ``LLMClient`` is configured.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from verdano.canonical import MappingEvidence, MappingResult
from verdano.canonical.models import register_stratum
from verdano.llm.client import strip_json_fences

if TYPE_CHECKING:
    from verdano.llm.client import LLMClient
    from verdano.mapping.resolver import MasterIndex

log = logging.getLogger(__name__)

register_stratum("llm_rerank", after="llm_augmented")

_SYSTEM_PROMPT = (
    "You are an expert in UK grocery/CPG product data. "
    "A deterministic system matched a retailer product to an ERP SKU. "
    "Your job is to VALIDATE or CORRECT that match. "
    "You will be given the retailer name, the system's pick, and alternative "
    "candidates from the ERP master. "
    "Reply ONLY with JSON: "
    '{"agrees": true/false, "sku": "<best_sku_or_null>", '
    '"confidence": <0.0-1.0>, "reason": "<brief explanation>"}'
)


def _build_rerank_prompt(
    retailer_name: str,
    current_sku: str,
    current_product_name: str,
    candidates: list[dict[str, str]],
) -> str:
    cand_lines = "\n".join(
        f"  - {c['sku']}: {c['name']}" for c in candidates
    )
    return (
        f'Retailer product: "{retailer_name}"\n'
        f"System's current match: {current_sku} ({current_product_name})\n\n"
        f"All ERP candidates:\n{cand_lines}\n\n"
        "Is the system's match correct? If not, which candidate is better?"
    )


@dataclass(frozen=True)
class ReRankResult:
    """Outcome of a single re-rank evaluation."""

    agrees: bool
    suggested_sku: str | None
    confidence: float
    reason: str


def should_rerank(
    mapping: MappingResult,
    *,
    rerank_threshold: float,
    rerank_strata: frozenset[str],
) -> bool:
    """Decide whether a cascade result qualifies for LLM re-ranking."""
    if mapping.state == "Unmapped" or mapping.erp_sku is None:
        return False
    if mapping.evidence is None:
        return False
    if mapping.evidence.stratum in rerank_strata:
        return True
    return mapping.confidence < rerank_threshold


def rerank_mapping(
    mapping: MappingResult,
    master: "MasterIndex",
    client: "LLMClient",
    *,
    top_n: int = 5,
    min_llm_confidence: float = 0.70,
) -> ReRankResult:
    """Ask the LLM whether the cascade's mapping is correct.

    Returns a ``ReRankResult``. On any LLM failure the result defaults to
    ``agrees=True`` so the original mapping is preserved (graceful degradation).
    """
    assert mapping.erp_sku is not None

    current_product = master.products.get(mapping.erp_sku)
    current_name = current_product.name if current_product else mapping.erp_sku

    all_products = list(master.products.values())
    candidates = [{"sku": p.sku, "name": p.name} for p in all_products[:top_n]]

    if mapping.erp_sku not in {c["sku"] for c in candidates}:
        candidates.append({"sku": mapping.erp_sku, "name": current_name})

    retailer_name = mapping.retailer_key.name

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_rerank_prompt(
                retailer_name, mapping.erp_sku, current_name, candidates
            ),
        },
    ]

    try:
        raw = client.complete(messages, temperature=0.0)
        parsed = json.loads(strip_json_fences(raw))
    except Exception:
        log.warning(
            "llm_rerank failed for %s — keeping original mapping",
            retailer_name,
            exc_info=True,
        )
        return ReRankResult(
            agrees=True,
            suggested_sku=None,
            confidence=0.0,
            reason="LLM call failed; defaulting to agree",
        )

    agrees: bool = bool(parsed.get("agrees", True))
    suggested_sku: str | None = parsed.get("sku")
    confidence: float = float(parsed.get("confidence", 0.0))
    reason: str = str(parsed.get("reason", ""))

    if not agrees and confidence < min_llm_confidence:
        return ReRankResult(
            agrees=True,
            suggested_sku=None,
            confidence=confidence,
            reason=f"LLM disagreed but confidence too low ({confidence:.2f}); keeping original",
        )

    return ReRankResult(
        agrees=agrees,
        suggested_sku=suggested_sku,
        confidence=confidence,
        reason=reason,
    )


def apply_rerank(
    mapping: MappingResult,
    rr: ReRankResult,
) -> MappingResult:
    """Return a potentially-modified ``MappingResult`` based on the re-rank outcome.

    If the LLM agrees, the original mapping is returned unchanged.
    If the LLM disagrees (high confidence), the state is downgraded to
    ``NeedsVerification`` and evidence is replaced with an ``llm_rerank``
    stratum so operators can see why the mapping was flagged.
    """
    if rr.agrees:
        return mapping

    return MappingResult(
        retailer_key=mapping.retailer_key,
        erp_sku=mapping.erp_sku,
        confidence=mapping.confidence,
        state="NeedsVerification",
        evidence=MappingEvidence(
            stratum="llm_rerank",
            matched_value=mapping.retailer_key.name,
            collision_count=mapping.evidence.collision_count if mapping.evidence else 1,
        ),
    )
