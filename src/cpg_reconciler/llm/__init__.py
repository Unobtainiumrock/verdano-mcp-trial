"""Provider-agnostic LLM integration layer.

Optional — if ``openai`` is not installed or no API key is configured,
all functions degrade gracefully (``create_llm_client`` returns ``None``).
"""

from cpg_reconciler.llm.client import (
    LLMClient,
    LLMSettings,
    OpenAIClient,
    create_llm_client,
    strip_json_fences,
)
from cpg_reconciler.llm.reranker import ReRankResult, apply_rerank, rerank_mapping, should_rerank

__all__ = [
    "LLMClient",
    "LLMSettings",
    "OpenAIClient",
    "ReRankResult",
    "apply_rerank",
    "create_llm_client",
    "rerank_mapping",
    "should_rerank",
    "strip_json_fences",
]
