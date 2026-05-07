"""count_clients — «сколько у меня клиентов» — counter + tappable list.

Renders the same client list the manual «👥 Клиенты» menu shows, with a
count prefix in the header. Tapping a button opens the client card via
the existing ClientCD(action="pick") flow.
"""

from __future__ import annotations

import html
from typing import Any, ClassVar

from src.bot.keyboards.client_picker import client_picker_kb
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
)
from src.storage.repositories.clients import ClientRepository


def _plural_clients(n: int) -> str:
    """Russian declension: 1 клиент / 2-4 клиента / 0,5+ клиентов."""
    if 11 <= (n % 100) <= 14:
        return "клиентов"
    last = n % 10
    if last == 1:
        return "клиент"
    if 2 <= last <= 4:
        return "клиента"
    return "клиентов"


class CountClientsAction:
    name: ClassVar[str] = "count_clients"
    description: ClassVar[str] = (
        "Показать всех клиентов с подсчётом. Используй для команд «сколько "
        "клиентов», «сколько у меня клиентов», «покажи клиентов»."
    )
    confirm_required: ClassVar[bool] = False
    confirm_label: ClassVar[str] = "✅ Сохранить"
    cancel_label: ClassVar[str] = "❌ Отменить"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        # Use the same listing the manual «👥 Клиенты» menu uses — last 20
        # by created_at — so behaviour matches the rest of the bot.
        clients = await ClientRepository(ctx.session).list_recent(limit=100)
        count = len(clients)
        if count == 0:
            return ActionResponse(
                result=ActionResult.EXECUTED,
                text="👥 У тебя пока нет клиентов в базе.",
            )
        # Cap the keyboard at 20 entries (Telegram limit safety + matches
        # the manual menu) but still report the true count in the header.
        visible = clients[:20]
        suffix = ""
        if count > len(visible):
            suffix = f" (показано первых {len(visible)})"
        text = (
            f"👥 У тебя <b>{count}</b> {_plural_clients(count)}{suffix}.\n"
            f"Выбери клиента чтобы открыть карточку:"
        )
        # Defensive: html-escape isn't applied here because client_picker_kb
        # builds its own labels safely via the keyboard module.
        _ = html  # silence unused import
        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=text,
            keyboard=client_picker_kb(recent=visible),
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError("count_clients is read-only — execute should not be called")
