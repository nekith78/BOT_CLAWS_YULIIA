"""Confirm-card keyboard for voice/text intake destructive actions.

Layout when `editable_fields` is None or empty (default — backwards-compat):

    [✅ Сохранить]
    [✏️ Изменить]   [❌ Отменить]

Layout when `editable_fields` is non-empty (dynamic per-action):

    [✏️ Изменить <field1>]   [✏️ Изменить <field2>]
    [✏️ Изменить <field3>]   [✏️ Изменить <field4>]
    [✏️ Изменить <field5>]
    [✅ Сохранить]
    [✏️ Изменить полностью]   [❌ Отменить]

Edit-buttons pack 2 per row; the standard footer (✅ alone, then
«Изменить полностью» + ❌) follows underneath.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import IntakeCD
from src.services.intent.types import EditableField


def confirm_card_kb(
    *,
    tag: str,
    editable_fields: list[EditableField] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if editable_fields:
        rows.extend(_build_edit_rows(tag=tag, fields=editable_fields))

    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Сохранить",
                callback_data=IntakeCD(action="confirm", tag=tag).pack(),
            )
        ]
    )

    # Footer: «Изменить полностью» (full-edit handoff stub) + ❌ Отменить.
    # Label switches to «Изменить» when there are no per-field buttons —
    # nothing to disambiguate against, keep the original short label.
    edit_full_label = "✏️ Изменить полностью" if editable_fields else "✏️ Изменить"
    rows.append(
        [
            InlineKeyboardButton(
                text=edit_full_label,
                callback_data=IntakeCD(action="edit", tag=tag).pack(),
            ),
            InlineKeyboardButton(
                text="❌ Отменить",
                callback_data=IntakeCD(action="cancel", tag=tag).pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_edit_rows(
    *,
    tag: str,
    fields: list[EditableField],
) -> list[list[InlineKeyboardButton]]:
    """Pack per-field edit buttons two-up. Odd count leaves the last
    row with one button, which keeps the layout balanced visually."""
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for field in fields:
        current.append(
            InlineKeyboardButton(
                text=f"✏️ Изменить {field.label.lower()}",
                callback_data=IntakeCD(
                    action="edit_field", tag=tag, field=field.key
                ).pack(),
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return rows
