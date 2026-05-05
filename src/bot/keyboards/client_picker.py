"""Recent clients + 🔍 Поиск + ➕ Новый клиент."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ClientCD
from src.storage.models import Client

# Sentinel client_id used to route "🔍 Поиск" — anything ≤ 0 is invalid as a real id.
SEARCH_SENTINEL = -1


def client_picker_kb(*, recent: list[Client]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in recent:
        rows.append(
            [
                InlineKeyboardButton(
                    text=c.name,
                    callback_data=ClientCD(action="pick", client_id=c.id).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔍 Поиск",
                callback_data=ClientCD(action="pick", client_id=SEARCH_SENTINEL).pack(),
            ),
            InlineKeyboardButton(
                text="➕ Новый клиент",
                callback_data=ClientCD(action="new").pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
