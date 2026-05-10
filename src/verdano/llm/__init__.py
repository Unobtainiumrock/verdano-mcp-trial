"""Provider-agnostic LLM integration layer.

Optional — if ``openai`` is not installed or no API key is configured,
all functions degrade gracefully (``create_llm_client`` returns ``None``).
"""

from verdano.llm.client import (
    LLMClient,
    LLMSettings,
    OpenAIClient,
    create_llm_client,
    strip_json_fences,
)

__all__ = [
    "LLMClient",
    "LLMSettings",
    "OpenAIClient",
    "create_llm_client",
    "strip_json_fences",
]
