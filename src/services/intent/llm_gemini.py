"""Gemini Flash LLM provider for intent parsing.

Uses the new `google-genai` SDK with function-calling: every Action's
ToolSpec becomes a FunctionDeclaration; the model picks one (or none)
and returns its args. We always set `temperature=0.0` for determinism —
this is a parser, not a creative task.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.services.intent.types import ParsedIntent, ToolSpec

log = logging.getLogger(__name__)


class GeminiLLM:
    def __init__(self, *, api_key: str, model: str = "gemini-2.5-flash") -> None:
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

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=text,
            config=gtypes.GenerateContentConfig(
                system_instruction=system,
                tools=[gtypes.Tool(function_declarations=function_decls)],
                temperature=0.0,
            ),
        )

        fc = _extract_function_call(response)
        if fc is None:
            log.info("gemini parse: no tool picked for %r", text)
            return ParsedIntent(tool_name=None, args={}, raw_text=text)

        args = dict(fc.args) if fc.args else {}
        log.info("gemini parse: tool=%s args=%s", fc.name, args)
        return ParsedIntent(tool_name=fc.name, args=args, raw_text=text)


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
