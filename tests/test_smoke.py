"""Smoke-тест: проверка что пакет корректно импортируется и валидация конфига работает."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest


@contextmanager
def _env(**values: str) -> Iterator[None]:
    """Временно подменить переменные окружения."""
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


def _required_minimum(**overrides: str) -> dict[str, str]:
    """Минимум для default-конфига: faster_whisper STT (без ключа) + Gemini LLM."""
    base = {
        "BOT_TOKEN": "12345:test-token",
        "OWNER_CHAT_ID": "111",
        "GEMINI_API_KEY": "fake-gemini-key",
    }
    # Очистить переменные, которые мог подложить cleanup-фейл предыдущего теста.
    for stale in ("STT_PROVIDER", "LLM_PROVIDER", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(stale, None)
    base.update(overrides)
    return base


def test_settings_load_with_minimum_env() -> None:
    from src.config import Settings

    with _env(**_required_minimum()):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.owner_chat_id == 111
    assert settings.stt_provider == "faster_whisper"
    assert settings.llm_provider == "gemini"
    assert settings.whisper_model_size == "small"
    assert settings.voice_max_duration_sec == 60
    assert settings.owner_tz == "Asia/Almaty"


def test_settings_rejects_gemini_without_key() -> None:
    from src.config import Settings

    env = _required_minimum()
    env.pop("GEMINI_API_KEY")
    with _env(**env), pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_rejects_openai_whisper_without_key() -> None:
    from src.config import Settings

    env = _required_minimum(STT_PROVIDER="openai_whisper")
    with _env(**env), pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_openai_whisper_with_key() -> None:
    from src.config import Settings

    env = _required_minimum(STT_PROVIDER="openai_whisper", OPENAI_API_KEY="sk-test")
    with _env(**env):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.stt_provider == "openai_whisper"


def test_settings_rejects_openai_mini_without_key() -> None:
    from src.config import Settings

    env = _required_minimum(LLM_PROVIDER="openai_mini")
    with _env(**env), pytest.raises(ValueError, match="OPENAI_API_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_openai_mini_with_key() -> None:
    from src.config import Settings

    env = _required_minimum(LLM_PROVIDER="openai_mini", OPENAI_API_KEY="sk-test")
    env.pop("GEMINI_API_KEY")
    with _env(**env):
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.llm_provider == "openai_mini"


def test_settings_rejects_anthropic_without_key() -> None:
    from src.config import Settings

    env = _required_minimum(LLM_PROVIDER="anthropic_haiku")
    with _env(**env), pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(_env_file=None)  # type: ignore[call-arg]
