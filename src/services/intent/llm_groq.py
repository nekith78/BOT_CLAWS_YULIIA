"""Groq Cloud LLM provider for intent parsing.

Groq's Chat Completions API is OpenAI-compatible — same `tools=[...]`,
`tool_choice="auto"`, same response shape. We reuse the official `openai`
SDK pointed at Groq's base URL.

Default model: `llama-3.3-70b-versatile` — Groq's flagship at the time
of writing; great function-calling, decent Russian, free tier 6000 RPD.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from src.services.intent.types import ParsedIntent, ToolSpec

log = logging.getLogger(__name__)


class GroqLLM:
    def __init__(
        self, *, api_key: str, model: str = "llama-3.3-70b-versatile"
    ) -> None:
        from openai import AsyncOpenAI

        # Same SDK as OpenAI — Groq's API is drop-in compatible.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self._model = model

    async def parse_intent(
        self,
        *,
        text: str,
        tools: list[ToolSpec],
        system: str,
        now_local: datetime,
    ) -> ParsedIntent:
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.params_schema,
                },
            }
            for t in tools
        ]

        response = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            tools=openai_tools,
            tool_choice="auto",
            temperature=0.0,
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            text_response = getattr(message, "content", None)
            log.info(
                "groq parse: no tool picked for %r, content=%r", text, text_response
            )
            return ParsedIntent(tool_name=None, args={}, raw_text=text)

        tc = tool_calls[0]
        try:
            args: dict[str, Any] = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            log.warning(
                "groq parse: bad JSON args from model: %r", tc.function.arguments
            )
            args = {}
        log.info("groq parse: tool=%s args=%s", tc.function.name, args)
        return ParsedIntent(tool_name=tc.function.name, args=args, raw_text=text)
