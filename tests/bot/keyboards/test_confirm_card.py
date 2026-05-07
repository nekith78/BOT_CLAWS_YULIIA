"""Tests for confirm_card_kb."""

from __future__ import annotations

from src.bot.callback_data import IntakeCD
from src.bot.keyboards.confirm_card import confirm_card_kb


def test_confirm_card_has_three_buttons_with_same_tag() -> None:
    kb = confirm_card_kb(tag="abc123")

    flat = [btn for row in kb.inline_keyboard for btn in row]
    assert len(flat) == 3

    actions = [IntakeCD.unpack(btn.callback_data).action for btn in flat]
    assert actions == ["confirm", "edit", "cancel"]

    tags = {IntakeCD.unpack(btn.callback_data).tag for btn in flat}
    assert tags == {"abc123"}


def test_confirm_card_layout_save_alone_then_edit_cancel() -> None:
    kb = confirm_card_kb(tag="t")
    assert len(kb.inline_keyboard) == 2
    assert len(kb.inline_keyboard[0]) == 1   # ✅ takes its own row
    assert len(kb.inline_keyboard[1]) == 2   # ✏️ + ❌ share the second row


# --- Edit-field button rendering (Plan #5 Task 1+2) ----------------------


def test_intake_cd_round_trips_edit_field() -> None:
    """The expanded callback factory should accept and recover edit_field
    actions with both `tag` and `field` payload."""
    packed = IntakeCD(action="edit_field", tag="abc", field="date").pack()
    decoded = IntakeCD.unpack(packed)
    assert decoded.action == "edit_field"
    assert decoded.tag == "abc"
    assert decoded.field == "date"


def test_intake_cd_round_trips_cancel_edit() -> None:
    packed = IntakeCD(action="cancel_edit", tag="abc").pack()
    decoded = IntakeCD.unpack(packed)
    assert decoded.action == "cancel_edit"
    assert decoded.tag == "abc"
    assert decoded.field == ""
