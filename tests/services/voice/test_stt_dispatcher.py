"""Tests for the `get_stt(settings)` dispatcher."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

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
        "GROQ_API_KEY": "gsk-fake",
    }
    for stale in (
        "STT_PROVIDER",
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    ):
        os.environ.pop(stale, None)
    base.update(overrides)
    return base


class _FakeWhisperModel:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


def test_dispatcher_returns_faster_whisper_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("faster_whisper.WhisperModel", _FakeWhisperModel)

    from src.config import Settings
    from src.services.voice.faster_whisper_stt import FasterWhisperSTT
    from src.services.voice.stt import get_stt

    with _env(**_base_env()):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    stt = get_stt(settings)
    assert isinstance(stt, FasterWhisperSTT)


class _FakeAsyncOpenAI:
    def __init__(self, *, api_key: str) -> None:
        self.audio = type("A", (), {"transcriptions": None})()


def test_dispatcher_returns_openai_whisper_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("openai.AsyncOpenAI", _FakeAsyncOpenAI)

    from src.config import Settings
    from src.services.voice.openai_whisper_stt import OpenAIWhisperSTT
    from src.services.voice.stt import get_stt

    with _env(
        **_base_env(STT_PROVIDER="openai_whisper", OPENAI_API_KEY="sk-test")
    ):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    stt = get_stt(settings)
    assert isinstance(stt, OpenAIWhisperSTT)
