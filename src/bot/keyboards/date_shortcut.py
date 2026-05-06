"""Date-step shortcuts: [Сегодня][Завтра][Послезавтра] / [🗑 Удалить клиента] / [📅 Календарь].

The "🗑 Удалить клиента" button sits between the day-shortcuts and the
calendar — opens the same delete-confirm flow used in 👥 Клиенты.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ClientCD, DateShortcutCD


def date_shortcut_kb(*, client_id: int | None = None) -> InlineKeyboardMarkup:
    """Build the date-step keyboard. When `client_id` is given, a delete
    button targeted at that client is inserted between the shortcuts and
    the calendar; without it (e.g. reschedule) the delete row is omitted.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="Сегодня",
                callback_data=DateShortcutCD(action="today").pack(),
            ),
            InlineKeyboardButton(
                text="Завтра",
                callback_data=DateShortcutCD(action="tomorrow").pack(),
            ),
            InlineKeyboardButton(
                text="Послезавтра",
                callback_data=DateShortcutCD(action="day_after").pack(),
            ),
        ],
    ]
    if client_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить клиента",
                    callback_data=ClientCD(action="delete", client_id=client_id).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="📅 Календарь",
                callback_data=DateShortcutCD(action="open_calendar").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
