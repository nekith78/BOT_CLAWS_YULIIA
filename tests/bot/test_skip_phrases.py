"""Smoke tests for `is_skip_phrase`."""

from __future__ import annotations

import pytest

from src.bot.skip_phrases import is_skip_phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "нет",
        "Нет",
        "  Нет  ",
        "нету",
        "пусто",
        "ничего",
        "Пропусти",
        "пропустить",
        "не надо",
        "без заметки",
        "no",
        "skip",
        "—",
        "-",
        "",
        "Нет.",
        "пусто!",
    ],
)
def test_recognised_as_skip(phrase: str) -> None:
    assert is_skip_phrase(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "френч",
        "гель-лак",
        "Маша",
        "16:30",
        "не приду в этот раз",  # contains «не» but is a real sentence
        "ничего себе!",          # «ничего» but as exclamation, length differs
    ],
)
def test_real_text_not_skip(phrase: str) -> None:
    assert is_skip_phrase(phrase) is False
