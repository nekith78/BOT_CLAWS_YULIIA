"""Recent clients + 🔍 Поиск + ➕ Новый клиент / 🗑 Удалить клиента."""

from __future__ import annotations

from typing import Literal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ClientCD, WizardCD
from src.storage.models import Client

# Sentinel client_id used to route "🔍 Поиск" — anything ≤ 0 is invalid as a real id.
SEARCH_SENTINEL = -1


def _label_for(client: Client, ordinal_by_id: dict[int, int]) -> str:
    """Display label rule:
    - has instagram → always "Имя (@insta)"
    - no instagram, name unique in this picker → "Имя"
    - no instagram, name duplicated in this picker → "Имя #N" (1-based, by id asc)
    """
    if client.instagram:
        return f"{client.name} (@{client.instagram})"
    ordinal = ordinal_by_id.get(client.id)
    if ordinal is None:
        return client.name
    return f"{client.name} #{ordinal}"


def _build_ordinals(clients: list[Client]) -> dict[int, int]:
    """Assign 1-based ordinals to clients sharing a (case-insensitive) name and
    having no instagram. Singletons are not in the result.
    """
    groups: dict[str, list[Client]] = {}
    for c in clients:
        if c.instagram:
            continue
        groups.setdefault(c.name.lower(), []).append(c)
    ordinal_by_id: dict[int, int] = {}
    for group in groups.values():
        if len(group) < 2:
            continue
        for ordinal, c in enumerate(sorted(group, key=lambda x: x.id), start=1):
            ordinal_by_id[c.id] = ordinal
    return ordinal_by_id


def client_picker_kb(
    *,
    recent: list[Client],
    mode: Literal["pick", "delete"] = "pick",
) -> InlineKeyboardMarkup:
    """Render the client picker.

    - mode="pick" (default): every client emits ClientCD(action="pick"); footer
      shows 🔍 Поиск, ➕ Новый клиент, 🗑 Удалить клиента.
    - mode="delete": every client emits ClientCD(action="delete"); footer shows
      only ← Назад.
    """
    ordinal_by_id = _build_ordinals(recent)
    action = "pick" if mode == "pick" else "delete"
    rows: list[list[InlineKeyboardButton]] = []
    for c in recent:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_label_for(c, ordinal_by_id),
                    callback_data=ClientCD(action=action, client_id=c.id).pack(),
                )
            ]
        )
    if mode == "pick":
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
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить клиента",
                    callback_data=WizardCD(action="edit").pack(),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="← Назад",
                    callback_data=WizardCD(action="back").pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
