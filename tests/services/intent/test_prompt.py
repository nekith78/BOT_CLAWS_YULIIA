"""Tests for `build_system_prompt`."""

from __future__ import annotations

from datetime import datetime


def test_prompt_embeds_today_date_and_weekday() -> None:
    from src.services.intent.prompt import build_system_prompt

    # Wednesday, 2026-05-06 at 10:00 Almaty time
    now = datetime(2026, 5, 6, 10, 0)
    prompt = build_system_prompt(now_local=now, tz="Asia/Almaty")

    assert "2026-05-06" in prompt
    assert "среда" in prompt
    assert "10:00" in prompt
    assert "Asia/Almaty" in prompt


def test_prompt_describes_relative_dates() -> None:
    from src.services.intent.prompt import build_system_prompt

    now = datetime(2026, 5, 7, 12, 0)
    prompt = build_system_prompt(now_local=now, tz="Asia/Almaty")

    assert "Завтра" in prompt or "завтра" in prompt
    assert "YYYY-MM-DD" in prompt
    assert "HH:MM" in prompt


def test_prompt_explicitly_forbids_calling_unsuitable_tools() -> None:
    from src.services.intent.prompt import build_system_prompt

    now = datetime(2026, 5, 6, 10, 0)
    prompt = build_system_prompt(now_local=now, tz="Asia/Almaty")

    # If the user said "привет", LLM must not invent a tool call.
    assert "не вызывай" in prompt.lower() or "не вызыв" in prompt.lower()
