"""E5 LLM-augmented entity resolution stratum handler.

Sits after E4 in the cascade. Sends top-N fuzzy candidates to the LLM with a
structured prompt asking for the best match + confidence.  Only registered when
an ``LLMClient`` is available — the cascade degrades gracefully without it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from verdano.canonical import MappingEvidence, MappingResult, RetailerProductKey
from verdano.canonical.models import register_stratum

if TYPE_CHECKING:
    from verdano.llm.client import LLMClient
    from verdano.mapping.resolver import MasterIndex, ResolverContext, StratumHandler

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an expert in UK grocery/CPG product data. "
    "Given a retailer product name and a list of ERP master candidates, "
    "select the BEST match. Reply ONLY with JSON: "
    '{"sku": "<best_sku_or_null>", "confidence": <0.0-1.0>}'
)


def _build_user_prompt(
    retailer_name: str, candidates: list[dict[str, str]]
) -> str:
    cand_lines = "\n".join(
        f"  - {c['sku']}: {c['name']}" for c in candidates
    )
    return (
        f"Retailer product: \"{retailer_name}\"\n\n"
        f"ERP master candidates:\n{cand_lines}\n\n"
        "Which candidate is the best match? If none are appropriate, "
        'return {"sku": null, "confidence": 0.0}.'
    )


def make_llm_stratum(
    client: "LLMClient",
    master: "MasterIndex",
    *,
    top_n: int = 5,
    min_confidence: float = 0.30,
) -> "StratumHandler":
    """Create an E5 stratum handler backed by the given LLM client."""

    register_stratum("E5", after="E4")

    def handler(
        ctx: "ResolverContext", key: RetailerProductKey
    ) -> MappingResult | None:
        fuzzy = ctx.master.fuzzy_search(key.name)
        if fuzzy is None:
            return None

        best_name, _ = fuzzy
        all_skus = ctx.master.skus_for_canonical_name(best_name)

        candidates: list[dict[str, str]] = []
        for sku in all_skus[:top_n]:
            product = master.products.get(sku)
            if product:
                candidates.append({"sku": sku, "name": product.name})

        if not candidates:
            return None

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(key.name, candidates)},
        ]

        try:
            raw = client.complete(messages, temperature=0.0)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(raw)
        except Exception:
            log.warning("E5 LLM stratum failed for %s — skipping", key.name, exc_info=True)
            return None

        chosen_sku: str | None = parsed.get("sku")
        conf: float = float(parsed.get("confidence", 0.0))

        if not chosen_sku or conf < min_confidence:
            return None

        if chosen_sku not in master.products:
            return None

        return ctx.build_result(key, chosen_sku, conf, "E5", key.name, 1)

    return handler
