"""Tests for the `get_llm(settings)` dispatcher."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest


@contextmanager
def _env(**values: str) -> Iterator[None]:
    saved: dict[str, str | None] = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _base_env(**overrides: str) -> dict[str, str]:
    base = {
        "BOT_TOKEN": "12345:test-token",
        "OWNER_CHAT_ID": "111",
        "GEMINI_API_KEY": "fake-gemini-key",
    }
    for stale in ("STT_PROVIDER", "LLM_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(stale, None)
    base.update(overrides)
    return base


class _FakeGenaiClient:
    def __init__(self, *, api_key: str) -> None:
        self.aio = None


def test_dispatcher_returns_gemini_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("google.genai.Client", _FakeGenaiClient)

    from src.config import Settings
    from src.services.intent.llm import get_llm
    from src.services.intent.llm_gemini import GeminiLLM

    with _env(**_base_env()):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    llm = get_llm(settings)
    assert isinstance(llm, GeminiLLM)


def test_dispatcher_returns_openai_mini_when_configured() -> None:
    from src.config import Settings
    from src.services.intent.llm import get_llm
    from src.services.intent.llm_openai import OpenAIMiniLLM

    with _env(
        **_base_env(LLM_PROVIDER="openai_mini", OPENAI_API_KEY="sk-test")
    ):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    llm = get_llm(settings)
    assert isinstance(llm, OpenAIMiniLLM)


def test_dispatcher_returns_anthropic_haiku_when_configured() -> None:
    from src.config import Settings
    from src.services.intent.llm import get_llm
    from src.services.intent.llm_anthropic import AnthropicHaikuLLM

    with _env(
        **_base_env(LLM_PROVIDER="anthropic_haiku", ANTHROPIC_API_KEY="ant-test")
    ):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    llm = get_llm(settings)
    assert isinstance(llm, AnthropicHaikuLLM)
