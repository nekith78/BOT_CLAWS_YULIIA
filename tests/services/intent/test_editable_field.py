"""Smoke tests for EditableField + ActionResponse.editable_fields."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.services.intent.types import (
    ActionResponse,
    ActionResult,
    EditableField,
)


def test_editable_field_is_frozen_and_supports_equality() -> None:
    a = EditableField(key="date", label="Дата", editor="calendar")
    b = EditableField(key="date", label="Дата", editor="calendar")
    assert a == b
    with pytest.raises(FrozenInstanceError):
        a.key = "time"  # type: ignore[misc]


def test_editable_field_text_input_carries_prompt() -> None:
    f = EditableField(
        key="note",
        label="Заметка",
        editor="text_input",
        prompt_text="Напиши заметку:",
    )
    assert f.editor == "text_input"
    assert f.prompt_text == "Напиши заметку:"


def test_action_response_editable_fields_default_is_none() -> None:
    """Backwards compat: existing actions that don't populate the new
    field continue to work as before — confirm-card stays 3-button."""
    resp = ActionResponse(result=ActionResult.CONFIRM, text="ok")
    assert resp.editable_fields is None


def test_action_response_carries_editable_fields_when_set() -> None:
    fields = [
        EditableField(key="date", label="Дата", editor="calendar"),
        EditableField(key="time", label="Время", editor="time_picker"),
    ]
    resp = ActionResponse(
        result=ActionResult.CONFIRM,
        text="Создать запись?",
        editable_fields=fields,
    )
    assert resp.editable_fields == fields
