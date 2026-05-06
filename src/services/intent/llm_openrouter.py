"""OpenRouter LLM provider for intent parsing.

OpenRouter is a model-aggregator with an OpenAI-compatible Chat Completions
endpoint and a real free tier (no profile-completion gating). We reuse the
official `openai` SDK pointed at OpenRouter's base URL.

Default model: `openai/gpt-oss-120b:free` — OpenAI's open-weights 120B
model routed free through OpenRouter; native function-calling, strong
Russian, broadly available across multiple upstream providers (less
likely to hit «no endpoints found» than provider-specific free slugs).

Free-tier models on OpenRouter share upstream capacity across all users.
A single 429 doesn't mean the key is broken — it means the upstream
provider is currently saturated. We retry once after a short sleep
before bubbling up.
"""

from __future__ import annotations

import asyncio
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
        model: str = "openai/gpt-oss-120b:free",
    ) -> None:
        from openai import AsyncOpenAI

        # OpenRouter is OpenAI-compatible. The headers below show up in
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

        response = await self._call_with_retry(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            openai_tools=openai_tools,
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

    async def _call_with_retry(
        self,
        *,
        messages: list[dict[str, str]],
        openai_tools: list[dict[str, Any]],
    ) -> Any:
        """Retry once on 429 — free-tier models on OpenRouter share upstream
        capacity across all users, so a transient 429 is the norm during
        peak load. One retry after 2 sec usually unblocks us; if the second
        attempt also fails the user gets a clear «перегружен» message."""
        from openai import RateLimitError

        attempts = 0
        last_exc: Exception | None = None
        while attempts < 2:
            try:
                return await self._client.chat.completions.create(  # type: ignore[call-overload]
                    model=self._model,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    temperature=0.0,
                )
            except RateLimitError as exc:
                last_exc = exc
                if attempts >= 1:
                    raise
                log.warning(
                    "openrouter 429 (upstream rate-limit) on attempt %d "
                    "— sleeping 2s and retrying",
                    attempts + 1,
                )
                await asyncio.sleep(2.0)
                attempts += 1
        assert last_exc is not None
        raise last_exc
