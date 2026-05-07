"""Confirm-card keyboard for voice/text intake destructive actions.

Three buttons always:

    [✅ Сохранить]
    [✏️ Изменить]   [❌ Отменить]

Per-field edit lives behind «✏️ Изменить» — a separate sub-menu shows
which fields are editable (rendered by `edit_field_picker_kb` in a
sibling module). This keeps the primary card uncluttered.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import IntakeCD


def confirm_card_kb(*, tag: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить",
                    callback_data=IntakeCD(action="confirm", tag=tag).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=IntakeCD(action="edit", tag=tag).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=IntakeCD(action="cancel", tag=tag).pack(),
                ),
            ],
        ]
    )
