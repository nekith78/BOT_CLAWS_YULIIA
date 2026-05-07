"""count_clients — read-only «сколько у меня клиентов» counter."""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import func, select

from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
)
from src.storage.models import Client


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
        "Посчитать сколько у тебя клиентов в базе. Используй для команд "
        "«сколько клиентов», «сколько у меня клиентов»."
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
        result = await ctx.session.execute(select(func.count(Client.id)))
        count = int(result.scalar_one() or 0)
        text = f"👥 У тебя <b>{count}</b> {_plural_clients(count)} в базе."
        return ActionResponse(result=ActionResult.EXECUTED, text=text)

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError("count_clients is read-only — execute should not be called")
