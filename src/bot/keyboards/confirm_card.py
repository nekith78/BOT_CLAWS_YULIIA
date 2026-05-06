"""Confirm-card keyboard for voice/text intake destructive actions.

Three buttons: ✅ Сохранить, ✏️ Изменить, ❌ Отменить. Each carries the
same `tag` so the server side can look up the pending action in FSM data.
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
                ),
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
