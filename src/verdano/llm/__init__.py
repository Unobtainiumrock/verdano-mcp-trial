"""Provider-agnostic LLM integration layer.

Optional — if ``openai`` is not installed or no API key is configured,
all functions degrade gracefully (``create_llm_client`` returns ``None``).
"""

from verdano.llm.client import LLMClient, OpenAIClient, create_llm_client

__all__ = ["LLMClient", "OpenAIClient", "create_llm_client"]
