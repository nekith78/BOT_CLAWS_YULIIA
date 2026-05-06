"""Two-step HH:MM picker: hour grid → minute grid (step 5).

Opened from the "Другое время" button on the main 30-min grid. Hours 9..20
mirror the main grid; minutes are 00,05,...,55. Both screens have a back
button (to grid / to hours).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import TimePartCD


def time_hour_picker_kb() -> InlineKeyboardMarkup:
    hours = list(range(9, 24))  # 9..23
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(hours), 4):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{h:02d}",
                    callback_data=TimePartCD(action="hour", hh=h).pack(),
                )
                for h in hours[i : i + 4]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад к слотам",
                callback_data=TimePartCD(action="back_to_grid").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_minute_picker_kb(*, hh: int) -> InlineKeyboardMarkup:
    minutes = list(range(0, 60, 5))  # 0, 5, ..., 55
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(minutes), 6):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{m:02d}",
                    callback_data=TimePartCD(action="minute", hh=hh, mm=m).pack(),
                )
                for m in minutes[i : i + 6]
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад к часам",
                callback_data=TimePartCD(action="back_to_hours").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
