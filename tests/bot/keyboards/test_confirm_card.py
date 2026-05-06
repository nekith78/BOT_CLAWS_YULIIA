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
