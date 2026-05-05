"""Date-step shortcuts: [Сегодня][Завтра][Послезавтра][📅 Календарь][⌨️ Текстом]."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import DateShortcutCD


def date_shortcut_kb() -> InlineKeyboardMarkup:
    def btn(text: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=text,
            callback_data=DateShortcutCD(action=action).pack(),
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn("Сегодня", "today"), btn("Завтра", "tomorrow"), btn("Послезавтра", "day_after")],
            [btn("📅 Календарь", "open_calendar"), btn("⌨️ Текстом", "text_input")],
        ]
    )
