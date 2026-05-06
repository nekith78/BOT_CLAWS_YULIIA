"""Anthropic Haiku LLM provider — optional, not part of MVP.

Stub raises NotImplementedError if someone configures it before the
implementation is added.
"""

from __future__ import annotations

from datetime import datetime

from src.services.intent.types import ParsedIntent, ToolSpec


class AnthropicHaikuLLM:
    def __init__(self, *, api_key: str, model: str = "claude-haiku-4-5") -> None:
        self._api_key = api_key
        self._model = model

    async def parse_intent(
        self,
        *,
        text: str,
        tools: list[ToolSpec],
        system: str,
        now_local: datetime,
    ) -> ParsedIntent:
        raise NotImplementedError(
            "AnthropicHaikuLLM is not yet implemented. "
            "Set LLM_PROVIDER=gemini or openai_mini for now."
        )
