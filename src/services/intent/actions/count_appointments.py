"""count_appointments — «сколько записей за период» — counter + tappable list.

Wraps `ListAppointmentsAction` so the resulting card mirrors the manual
«📋 Записи» menu — same per-appointment buttons, same period-aware
window — and prepends a count summary header.
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.services.intent.actions.list_appointments import ListAppointmentsAction
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
)


def _plural_appts(n: int) -> str:
    if 11 <= (n % 100) <= 14:
        return "записей"
    last = n % 10
    if last == 1:
        return "запись"
    if 2 <= last <= 4:
        return "записи"
    return "записей"


class CountAppointmentsAction:
    name: ClassVar[str] = "count_appointments"
    description: ClassVar[str] = (
        "Показать сколько записей за период с полным списком. Используй "
        "для команд «сколько записей на сегодня», «сколько у меня записей "
        "на этой неделе», «сколько записей в этом месяце»."
    )
    confirm_required: ClassVar[bool] = False
    confirm_label: ClassVar[str] = "✅ Сохранить"
    cancel_label: ClassVar[str] = "❌ Отменить"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "enum": ["today", "tomorrow", "week", "month", "all", "date"],
                "description": (
                    "today=сегодня, tomorrow=завтра, week=ближайшие 7 дней, "
                    "month=текущий месяц, all=все будущие, date=конкретный день"
                ),
            },
            "date": {
                "type": "string",
                "description": "YYYY-MM-DD — обязателен только если period=date",
            },
        },
        "required": ["period"],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        # Reuse list_appointments' window math, hydration, and keyboard
        # rendering. The only thing we add is the count prefix.
        list_resp = await ListAppointmentsAction().plan(ctx, args)
        if list_resp.result is not ActionResult.EXECUTED:
            return list_resp

        snapshot = list_resp.context_snapshot or {}
        items = snapshot.get("appointments") or []
        count = len(items)

        if count == 0:
            return list_resp  # «Записей нет» message kept verbatim

        prefix = f"📊 Найдено: <b>{count}</b> {_plural_appts(count)}\n\n"
        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=prefix + list_resp.text,
            keyboard=list_resp.keyboard,
            context_snapshot=list_resp.context_snapshot,
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError(
            "count_appointments is read-only — execute should not be called"
        )
