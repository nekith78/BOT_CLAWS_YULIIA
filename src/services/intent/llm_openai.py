"""OpenAI gpt-4o-mini LLM fallback.

Stub — full implementation lands in Plan #4 Task 5.
"""

from __future__ import annotations

from datetime import datetime

from src.services.intent.types import ParsedIntent, ToolSpec


class OpenAIMiniLLM:
    def __init__(self, *, api_key: str, model: str = "gpt-4o-mini") -> None:
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
        raise NotImplementedError("OpenAIMiniLLM lands in Plan #4 Task 5")
