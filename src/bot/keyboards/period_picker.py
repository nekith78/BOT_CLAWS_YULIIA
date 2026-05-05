"""Period filter for lists and client history."""

from __future__ import annotations

from typing import Literal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import PeriodCD


def period_picker_kb(
    *,
    scope: Literal["lists", "client"],
    scope_id: int = 0,
) -> InlineKeyboardMarkup:
    def btn(text: str, kind: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=text,
            callback_data=PeriodCD(
                kind=kind,
                scope=scope,
                scope_id=scope_id,
            ).pack(),
        )

    rows = [
        [btn("Сегодня", "today"), btn("Неделя", "week"), btn("Месяц", "month")],
        [btn("Все", "all"), btn("📅 Дата", "date")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
