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


def test_prompt_includes_few_shot_examples_block() -> None:
    """The ПРИМЕРЫ section grounds the LLM with concrete fragments —
    Plan #5 Task 3 verifies all 7 actions are represented + chitchat."""
    from src.services.intent.prompt import build_system_prompt

    now = datetime(2026, 5, 6, 10, 0)
    prompt = build_system_prompt(now_local=now, tz="Asia/Almaty")

    assert "ПРИМЕРЫ" in prompt
    # Each tool name appears at least once in an example.
    for tool in (
        "create_appointment",
        "list_appointments",
        "list_client_history",
        "move_appointment",
        "cancel_appointment",
        "edit_note",
        "delete_client",
        "count_clients",
        "count_appointments",
        "count_client_appointments",
        "bulk_cancel_by_date",
        "bulk_cancel_by_client",
        "bulk_delete_clients",
    ):
        assert tool in prompt, f"missing example for {tool}"
    # Chit-chat negative example present.
    assert "привет" in prompt
