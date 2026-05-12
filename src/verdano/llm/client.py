"""Provider-agnostic LLM client.

Uses the OpenAI SDK with a configurable ``base_url`` so any OpenAI-compatible
API (OpenAI, Azure, Ollama, vLLM, LiteLLM) works without code changes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import SecretStr

log = logging.getLogger(__name__)


def strip_json_fences(raw: str) -> str:
    """Remove markdown code fences (```json ... ```) wrapping a JSON payload."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    return raw


@runtime_checkable
class LLMClient(Protocol):
    """Minimal contract consumed by the resolver and depot fallbacks."""

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Return the assistant-message text for the given conversation."""
        ...


class OpenAIClient:
    """Concrete client backed by the ``openai`` SDK."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "Install the 'llm' extra: `pip install verdano-mcp[llm]`"
            ) from exc

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            **kwargs,
        )
        content = resp.choices[0].message.content
        return content or ""

    def complete_json(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> dict[str, Any]:
        """Complete and parse the response as JSON."""
        raw = self.complete(messages, **kwargs)
        return json.loads(strip_json_fences(raw))  # type: ignore[no-any-return]


class LLMSettings(Protocol):
    """Minimal contract for the settings object consumed by the factory."""

    llm_api_key: SecretStr
    llm_base_url: str
    llm_model: str


def create_llm_client(settings: LLMSettings) -> LLMClient | None:
    """Factory: build an LLM client from ``Settings``, or ``None`` if unconfigured."""
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if not api_key:
        log.info("No LLM API key configured — LLM features disabled")
        return None

    return OpenAIClient(
        api_key=api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )
