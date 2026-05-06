"""LLM abstraction for intent parsing.

`LLMProvider` is the surface every concrete provider implements.
`get_llm(settings)` is the dispatcher used at startup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from src.config import Settings
from src.services.intent.types import ParsedIntent, ToolSpec


@runtime_checkable
class LLMProvider(Protocol):
    async def parse_intent(
        self,
        *,
        text: str,
        tools: list[ToolSpec],
        system: str,
        now_local: datetime,
    ) -> ParsedIntent: ...


def get_llm(settings: Settings) -> LLMProvider:
    """Construct the LLM provider configured in `settings`."""
    if settings.llm_provider == "gemini":
        from src.services.intent.llm_gemini import GeminiLLM

        if settings.gemini_api_key is None:
            raise RuntimeError("GEMINI_API_KEY required for gemini")
        # gemini-2.0-flash is more reliable on the free tier than 2.5-flash,
        # which gets throttled hard during peak load (frequent 503s).
        model = settings.llm_model or "gemini-2.0-flash"
        return GeminiLLM(
            api_key=settings.gemini_api_key.get_secret_value(),
            model=model,
        )
    if settings.llm_provider == "openai_mini":
        from src.services.intent.llm_openai import OpenAIMiniLLM

        if settings.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY required for openai_mini")
        model = settings.llm_model or "gpt-4o-mini"
        return OpenAIMiniLLM(
            api_key=settings.openai_api_key.get_secret_value(),
            model=model,
        )
    if settings.llm_provider == "anthropic_haiku":
        from src.services.intent.llm_anthropic import AnthropicHaikuLLM

        if settings.anthropic_api_key is None:
            raise RuntimeError("ANTHROPIC_API_KEY required for anthropic_haiku")
        model = settings.llm_model or "claude-haiku-4-5"
        return AnthropicHaikuLLM(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=model,
        )
    raise AssertionError(f"unknown llm_provider: {settings.llm_provider}")
