"""Inline calendar — month grid with month-nav."""

from __future__ import annotations

import calendar as _cal
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import CalendarCD

_MONTHS_RU = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
_WEEKDAY_HEADER = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
_NOOP = CalendarCD(action="noop").pack()


def calendar_kb(*, anchor: date) -> InlineKeyboardMarkup:
    """Build a month grid for `anchor.year/anchor.month`. Day cells emit
    `CalendarCD(action="pick", iso_date=YYYY-MM-DD)`. Nav arrows emit
    `CalendarCD(action="nav", nav="prev"|"next", iso_date=anchor.month_first)`.
    """
    year, month = anchor.year, anchor.month
    title = f"{_MONTHS_RU[month]} {year}"
    header = [InlineKeyboardButton(text=title, callback_data=_NOOP)]
    weekdays = [
        InlineKeyboardButton(text=w, callback_data=_NOOP) for w in _WEEKDAY_HEADER
    ]

    cal = _cal.Calendar(firstweekday=0)
    rows: list[list[InlineKeyboardButton]] = [header, weekdays]
    for week in cal.monthdayscalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data=_NOOP))
            else:
                iso = f"{year:04d}-{month:02d}-{day:02d}"
                row.append(
                    InlineKeyboardButton(
                        text=str(day),
                        callback_data=CalendarCD(action="pick", iso_date=iso).pack(),
                    )
                )
        rows.append(row)

    first = date(year, month, 1).isoformat()
    nav = [
        InlineKeyboardButton(
            text="«",
            callback_data=CalendarCD(action="nav", nav="prev", iso_date=first).pack(),
        ),
        InlineKeyboardButton(text=" ", callback_data=_NOOP),
        InlineKeyboardButton(
            text="»",
            callback_data=CalendarCD(action="nav", nav="next", iso_date=first).pack(),
        ),
    ]
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)
