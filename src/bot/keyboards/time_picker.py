"""Time grid 09:00–20:30 with 30-min step + 'Другое время'."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import TimeCD


def time_picker_kb() -> InlineKeyboardMarkup:
    slots: list[str] = []
    for hh in range(9, 21):
        slots.append(f"{hh:02d}:00")
        slots.append(f"{hh:02d}:30")
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(slots), 4):
        rows.append(
            [
                InlineKeyboardButton(text=s, callback_data=TimeCD(hhmm=s).pack())
                for s in slots[i : i + 4]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Другое время",
                callback_data=TimeCD(hhmm="custom").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
