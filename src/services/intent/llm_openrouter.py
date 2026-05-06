"""OpenRouter LLM provider for intent parsing.

OpenRouter is a model-aggregator with an OpenAI-compatible Chat Completions
endpoint and a real free tier (no profile-completion gating like Groq's).
We reuse the official `openai` SDK pointed at OpenRouter's base URL.

Default model: `meta-llama/llama-3.3-70b-instruct:free` — free tier,
~200 requests/day, good function-calling, decent Russian. To swap, set
`LLM_MODEL=...` in `.env` (paid options like
`anthropic/claude-haiku-4.5` or `openai/gpt-4o-mini` work transparently).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from src.services.intent.types import ParsedIntent, ToolSpec

log = logging.getLogger(__name__)


class OpenRouterLLM:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "meta-llama/llama-3.3-70b-instruct:free",
    ) -> None:
        from openai import AsyncOpenAI

        # OpenRouter is OpenAI-compatible. The optional headers below show up in
        # OpenRouter's leaderboards / per-app analytics — purely cosmetic.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/nekith78/BOT_CLAWS_YULIIA",
                "X-Title": "BOT_CLAWS_YULIIA",
            },
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
                "openrouter parse: no tool picked for %r, content=%r",
                text, text_response,
            )
            return ParsedIntent(tool_name=None, args={}, raw_text=text)

        tc = tool_calls[0]
        try:
            args: dict[str, Any] = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            log.warning(
                "openrouter parse: bad JSON args from model: %r", tc.function.arguments
            )
            args = {}
        log.info("openrouter parse: tool=%s args=%s", tc.function.name, args)
        return ParsedIntent(tool_name=tc.function.name, args=args, raw_text=text)
