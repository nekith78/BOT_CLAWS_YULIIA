"""OpenAI gpt-4o-mini LLM provider for intent parsing.

Uses chat-completions function-calling: each ToolSpec becomes a `tools`
entry, `tool_choice="auto"` lets the model pick none-or-one. We always
set temperature=0.0 — this is a parser, not a creative task.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from src.services.intent.types import ParsedIntent, ToolSpec

log = logging.getLogger(__name__)


class OpenAIMiniLLM:
    def __init__(self, *, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
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

        # OpenAI SDK's `create` is overloaded with TypedDicts that don't accept
        # plain `dict[str, str]`; the runtime accepts what we pass. Cast to
        # silence mypy without polluting our internal types.
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
            log.info("openai_mini parse: no tool picked for %r", text)
            return ParsedIntent(tool_name=None, args={}, raw_text=text)

        tc = tool_calls[0]
        try:
            args: dict[str, Any] = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            log.warning(
                "openai_mini parse: bad JSON args from model: %r", tc.function.arguments
            )
            args = {}
        log.info("openai_mini parse: tool=%s args=%s", tc.function.name, args)
        return ParsedIntent(tool_name=tc.function.name, args=args, raw_text=text)
