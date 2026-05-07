"""Tests for appointment_picker_kb — used by the smart-fallback question
loop when the second brain needs the user to pick which record to act on."""

from __future__ import annotations

from src.bot.callback_data import IntakeCD
from src.bot.keyboards.appointment_picker import appointment_picker_kb
from src.services.intent.text_normalizer import ClarifyOption


def test_renders_one_row_per_option_plus_cancel_footer() -> None:
    options = [
        ClarifyOption(label="Ира — 08.05 10:00", value={"appointment_id": 1}),
        ClarifyOption(label="Маша — 08.05 14:30", value={"appointment_id": 2}),
    ]
    kb = appointment_picker_kb(options=options, tag="abc12345")

    # 2 option rows + 1 footer row.
    assert len(kb.inline_keyboard) == 3
    # Each option row has exactly one button.
    for row in kb.inline_keyboard[:2]:
        assert len(row) == 1
    # First option's callback round-trips into IntakeCD(action="sb_pick", index=0).
    cd0 = IntakeCD.unpack(kb.inline_keyboard[0][0].callback_data or "")
    assert cd0.action == "sb_pick"
    assert cd0.tag == "abc12345"
    assert cd0.index == 0
    # Second option = index 1.
    cd1 = IntakeCD.unpack(kb.inline_keyboard[1][0].callback_data or "")
    assert cd1.index == 1
    # Footer = cancel_edit.
    cancel_btn = kb.inline_keyboard[-1][0]
    cd_cancel = IntakeCD.unpack(cancel_btn.callback_data or "")
    assert cd_cancel.action == "cancel_edit"
    assert "Отмена" in cancel_btn.text


def test_empty_options_still_has_cancel_footer() -> None:
    kb = appointment_picker_kb(options=[], tag="xyz")
    assert len(kb.inline_keyboard) == 1  # just the cancel
    cd = IntakeCD.unpack(kb.inline_keyboard[0][0].callback_data or "")
    assert cd.action == "cancel_edit"
