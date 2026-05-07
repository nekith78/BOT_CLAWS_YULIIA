"""Sub-menu shown after «✏️ Изменить» on a confirm-card — lets the user
pick which field to edit.

Buttons carry the action's editable-field labels («Имя клиента»,
«Дата», «Время», «Заметка», «Instagram», ...) packed two per row, plus
a «← Назад» back-button that returns to the confirm-card unchanged.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import IntakeCD
from src.services.intent.types import EditableField


def edit_field_picker_kb(
    *, tag: str, fields: list[EditableField]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for f in fields:
        current.append(
            InlineKeyboardButton(
                text=f.label,
                callback_data=IntakeCD(
                    action="edit_field", tag=tag, field=f.key
                ).pack(),
            )
        )
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад",
                callback_data=IntakeCD(action="back_to_confirm", tag=tag).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
