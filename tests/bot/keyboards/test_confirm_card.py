"""Tests for confirm_card_kb + edit_field_picker_kb.

Confirm-card always renders just 3 buttons (✅ / ✏️ / ❌). The per-field
edit submenu lives in `edit_field_picker_kb` and surfaces only after
the user taps «✏️ Изменить» — keeps the primary card uncluttered.
"""

from __future__ import annotations

from src.bot.callback_data import IntakeCD
from src.bot.keyboards.confirm_card import confirm_card_kb
from src.bot.keyboards.edit_field_picker import edit_field_picker_kb
from src.services.intent.types import EditableField


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


# --- IntakeCD round-trip for new actions --------------------------------


def test_intake_cd_round_trips_edit_field() -> None:
    packed = IntakeCD(action="edit_field", tag="abc", field="date").pack()
    decoded = IntakeCD.unpack(packed)
    assert decoded.action == "edit_field"
    assert decoded.tag == "abc"
    assert decoded.field == "date"


def test_intake_cd_round_trips_cancel_edit() -> None:
    packed = IntakeCD(action="cancel_edit", tag="abc").pack()
    decoded = IntakeCD.unpack(packed)
    assert decoded.action == "cancel_edit"


def test_intake_cd_round_trips_back_to_confirm() -> None:
    packed = IntakeCD(action="back_to_confirm", tag="abc").pack()
    decoded = IntakeCD.unpack(packed)
    assert decoded.action == "back_to_confirm"


# --- edit_field_picker_kb (sub-menu after «✏️ Изменить») ----------------


def test_edit_field_picker_packs_two_per_row_with_back_button() -> None:
    """Each EditableField → one button labelled with `label` only (no
    «Изменить» prefix). Buttons pack 2 per row, terminated by «← Назад»."""
    fields = [
        EditableField(key="client_name", label="Имя клиента", editor="text_input"),
        EditableField(key="date", label="Дата", editor="calendar"),
        EditableField(key="time", label="Время", editor="time_picker"),
        EditableField(key="note", label="Заметка", editor="text_input"),
        EditableField(key="instagram", label="Instagram", editor="text_input"),
    ]
    kb = edit_field_picker_kb(tag="abc", fields=fields)

    # 3 field-rows (2-2-1) + 1 back-row.
    assert len(kb.inline_keyboard) == 4
    assert len(kb.inline_keyboard[0]) == 2
    assert len(kb.inline_keyboard[1]) == 2
    assert len(kb.inline_keyboard[2]) == 1
    assert len(kb.inline_keyboard[3]) == 1

    field_btns = (
        kb.inline_keyboard[0] + kb.inline_keyboard[1] + kb.inline_keyboard[2]
    )
    # No «Изменить» prefix on the buttons.
    assert [b.text for b in field_btns] == [
        "Имя клиента", "Дата", "Время", "Заметка", "Instagram"
    ]
    # Each button carries action=edit_field with the matching field key.
    decoded = [IntakeCD.unpack(b.callback_data) for b in field_btns]
    assert all(d.action == "edit_field" and d.tag == "abc" for d in decoded)
    assert [d.field for d in decoded] == [
        "client_name", "date", "time", "note", "instagram"
    ]

    back_btn = kb.inline_keyboard[3][0]
    assert back_btn.text == "← Назад"
    assert IntakeCD.unpack(back_btn.callback_data).action == "back_to_confirm"
