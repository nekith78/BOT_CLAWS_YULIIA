"""Gemini Flash LLM provider for intent parsing.

Uses the new `google-genai` SDK with function-calling: every Action's
ToolSpec becomes a FunctionDeclaration; the model picks one (or none)
and returns its args. We always set `temperature=0.0` for determinism —
this is a parser, not a creative task.

503 «high demand» errors retry once with backoff before bubbling up;
the SDK's built-in tenacity retry gives up too fast for the free tier.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from src.services.intent.types import ParsedIntent, ToolSpec

log = logging.getLogger(__name__)


class GeminiLLM:
    def __init__(self, *, api_key: str, model: str = "gemini-2.0-flash") -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def parse_intent(
        self,
        *,
        text: str,
        tools: list[ToolSpec],
        system: str,
        now_local: datetime,
    ) -> ParsedIntent:
        from google.genai import types as gtypes

        function_decls = [
            gtypes.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=t.params_schema,
            )
            for t in tools
        ]
        config = gtypes.GenerateContentConfig(
            system_instruction=system,
            tools=[gtypes.Tool(function_declarations=function_decls)],
            temperature=0.0,
        )

        response = await self._call_with_retry(text=text, config=config)

        fc = _extract_function_call(response)
        if fc is None:
            # When the model declines a tool it usually returns text instead.
            # Logging the text reveals refusal reasons (safety filters,
            # confused tool list, malformed parameters schema, etc.) so we
            # can iterate on the prompt and on tool descriptions.
            text_response = getattr(response, "text", None)
            log.info(
                "gemini parse: no tool picked for %r, text=%r",
                text, text_response,
            )
            return ParsedIntent(tool_name=None, args={}, raw_text=text)

        args = dict(fc.args) if fc.args else {}
        log.info("gemini parse: tool=%s args=%s", fc.name, args)
        return ParsedIntent(tool_name=fc.name, args=args, raw_text=text)

    async def _call_with_retry(self, *, text: str, config: Any) -> Any:
        """Single retry on 503 / overload — Google's free tier flips between
        «available» and «high demand» on a roughly 30-sec cycle, so a brief
        sleep often unblocks us.
        """
        from google.genai.errors import ServerError

        attempts = 0
        last_exc: Exception | None = None
        while attempts < 2:
            try:
                return await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=text,
                    config=config,
                )
            except ServerError as exc:
                last_exc = exc
                if exc.code != 503 or attempts >= 1:
                    raise
                log.warning(
                    "gemini 503 (overload) on attempt %d — sleeping 2s and retrying",
                    attempts + 1,
                )
                await asyncio.sleep(2.0)
                attempts += 1
        # Unreachable, but keeps type-checkers happy.
        assert last_exc is not None
        raise last_exc


def _extract_function_call(response: Any) -> Any:
    """Pull the first FunctionCall out of a Gemini response, regardless of
    where the SDK exposes it. Returns None if the model didn't call any
    function."""
    fcs = getattr(response, "function_calls", None)
    if fcs:
        return fcs[0]
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                return fc
    return None
