"""OpenRouter LLM provider for intent parsing + key-quota helper.

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
from datetime import date, datetime, timezone
from typing import Any

import httpx

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
        # Local daily request counter — OpenRouter doesn't expose per-:free-model
        # daily count via API, so we count ourselves. Counter resets at 00:00 UTC.
        # On bot restart it resets too (worst case /quota under-counts for a day).
        self._daily_used = 0
        self._counter_day: date | None = None

    @property
    def model(self) -> str:
        return self._model

    def daily_used(self) -> int:
        """Requests this OpenRouter client made today (UTC). Reset at midnight."""
        today = datetime.now(tz=timezone.utc).date()
        if self._counter_day != today:
            return 0
        return self._daily_used

    def _bump_counter(self) -> None:
        today = datetime.now(tz=timezone.utc).date()
        if self._counter_day != today:
            self._daily_used = 0
            self._counter_day = today
        self._daily_used += 1

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
                response = await self._client.chat.completions.create(  # type: ignore[call-overload]
                    model=self._model,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    temperature=0.0,
                )
            except RateLimitError as exc:
                # OR counts even rate-limited calls against the daily quota.
                self._bump_counter()
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
                continue
            self._bump_counter()
            return response
        assert last_exc is not None
        raise last_exc


async def fetch_quota(api_key: str) -> dict[str, Any]:
    """Hit OpenRouter's GET /api/v1/auth/key for credit usage + free-tier
    status. Used by the /quota bot command. Raises httpx errors on
    network / auth failure — caller decides how to surface them.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        resp.raise_for_status()
        payload = resp.json()
    data = payload.get("data") or {}
    return data if isinstance(data, dict) else {}
