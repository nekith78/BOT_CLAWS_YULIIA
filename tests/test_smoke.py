"""Smoke-тест: проверка что пакет корректно импортируется и валидация конфига работает."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

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
    base = {
        "BOT_TOKEN": "12345:test-token",
        "OWNER_CHAT_ID": "111",
        "STT_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-test",
    }
    base.update(overrides)
    return base


def test_settings_load_with_minimum_env() -> None:
    from src.config import load_settings

    with _env(**_required_minimum()):
        settings = load_settings()

    assert settings.owner_chat_id == 111
    assert settings.stt_provider == "openai"
    assert settings.owner_tz == "Asia/Almaty"


def test_settings_rejects_openai_without_key() -> None:
    from src.config import load_settings

    env = _required_minimum()
    env.pop("OPENAI_API_KEY")
    with _env(**env), pytest.raises(ValueError, match="OPENAI_API_KEY"):
        load_settings()


def test_settings_rejects_yandex_without_keys() -> None:
    from src.config import load_settings

    env = _required_minimum(STT_PROVIDER="yandex")
    env.pop("OPENAI_API_KEY")
    with _env(**env), pytest.raises(ValueError, match="YANDEX"):
        load_settings()


def test_settings_yandex_with_keys() -> None:
    from src.config import load_settings

    env = _required_minimum(
        STT_PROVIDER="yandex",
        YANDEX_API_KEY="AQVN-test",
        YANDEX_FOLDER_ID="folder-test",
        LLM_API_KEY="sk-test",
    )
    env.pop("OPENAI_API_KEY")
    with _env(**env):
        settings = load_settings()

    assert settings.stt_provider == "yandex"
    assert settings.yandex_folder_id == "folder-test"
