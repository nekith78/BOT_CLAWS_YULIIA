"""Tests for confirm_card_kb."""

from __future__ import annotations

from src.bot.callback_data import IntakeCD
from src.bot.keyboards.confirm_card import confirm_card_kb
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


def test_confirm_card_with_no_editable_fields_keeps_old_layout() -> None:
    """Legacy 3-button layout stays for actions that don't declare
    editable fields (cancel, delete, etc.)."""
    kb_default = confirm_card_kb(tag="t")
    kb_explicit_none = confirm_card_kb(tag="t", editable_fields=None)
    kb_empty = confirm_card_kb(tag="t", editable_fields=[])

    for kb in (kb_default, kb_explicit_none, kb_empty):
        flat = [btn for row in kb.inline_keyboard for btn in row]
        assert len(flat) == 3
        actions = [IntakeCD.unpack(btn.callback_data).action for btn in flat]
        assert actions == ["confirm", "edit", "cancel"]


def test_confirm_card_with_edit_fields_renders_edit_buttons() -> None:
    """Each editable field becomes a button with action=edit_field +
    matching `field` payload. Buttons pack 2-per-row above the footer."""
    fields = [
        EditableField(key="client_name", label="Имя клиента", editor="client_picker"),
        EditableField(key="date", label="Дата", editor="calendar"),
        EditableField(key="time", label="Время", editor="time_picker"),
        EditableField(key="note", label="Заметка", editor="text_input"),
        EditableField(key="instagram", label="Instagram", editor="text_input"),
    ]
    kb = confirm_card_kb(tag="abc", editable_fields=fields)

    # Expected rows: 3 edit-rows (2-2-1) + ✅ + footer (Изменить полностью + ❌).
    assert len(kb.inline_keyboard) == 5
    assert len(kb.inline_keyboard[0]) == 2  # client_name + date
    assert len(kb.inline_keyboard[1]) == 2  # time + note
    assert len(kb.inline_keyboard[2]) == 1  # instagram alone
    assert len(kb.inline_keyboard[3]) == 1  # ✅
    assert len(kb.inline_keyboard[4]) == 2  # Изменить полностью + ❌

    # Each edit button carries the right field key.
    edit_btns = (
        kb.inline_keyboard[0] + kb.inline_keyboard[1] + kb.inline_keyboard[2]
    )
    decoded = [IntakeCD.unpack(b.callback_data) for b in edit_btns]
    assert all(d.action == "edit_field" and d.tag == "abc" for d in decoded)
    assert [d.field for d in decoded] == [
        "client_name", "date", "time", "note", "instagram"
    ]


def test_confirm_card_full_edit_label_changes_with_fields() -> None:
    """Without editable fields the button reads «✏️ Изменить» (legacy);
    with fields it reads «✏️ Изменить полностью» to disambiguate from
    the per-field edit buttons above."""
    kb_no_fields = confirm_card_kb(tag="t")
    edit_btn = kb_no_fields.inline_keyboard[1][0]
    assert edit_btn.text == "✏️ Изменить"

    kb_with_fields = confirm_card_kb(
        tag="t",
        editable_fields=[EditableField(key="date", label="Дата", editor="calendar")],
    )
    full_edit_btn = kb_with_fields.inline_keyboard[-1][0]
    assert full_edit_btn.text == "✏️ Изменить полностью"
