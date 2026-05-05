"""Per-appointment card actions: Перенести / Заметка / Отменить / Закрыть."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ApptCD


def appointment_card_kb(*, appointment_id: int) -> InlineKeyboardMarkup:
    def cd(action: str) -> str:
        return ApptCD(
            action=action,
            appointment_id=appointment_id,
        ).pack()

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Перенести", callback_data=cd("move")),
                InlineKeyboardButton(text="Заметка", callback_data=cd("note")),
            ],
            [
                InlineKeyboardButton(text="Отменить", callback_data=cd("cancel")),
                InlineKeyboardButton(text="Закрыть", callback_data=cd("close")),
            ],
        ]
    )
