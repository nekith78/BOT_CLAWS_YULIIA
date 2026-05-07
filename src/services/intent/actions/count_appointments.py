"""count_appointments — read-only «сколько записей за период» counter."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, ClassVar

from sqlalchemy import and_, func, select

from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
)
from src.storage.models import Appointment

_PERIOD_LABELS = {
    "today": "сегодня",
    "tomorrow": "завтра",
    "week": "на этой неделе",
    "month": "в этом месяце",
    "all": "всего (будущих)",
    "date": "на эту дату",
}


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
        "Посчитать сколько записей за период. Используй для команд "
        "«сколько записей на сегодня», «сколько у меня записей на этой неделе», "
        "«сколько записей в этом месяце»."
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
        period = (args.get("period") or "").strip()
        if period not in _PERIOD_LABELS:
            return ActionResponse(
                result=ActionResult.FAIL,
                text=f"Не понял период: {period!r}.",
            )

        anchor: date | None = None
        if period == "date":
            try:
                anchor = date.fromisoformat(args.get("date") or "")
            except ValueError:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text="Не разобрал дату. Формат: YYYY-MM-DD.",
                )

        start_utc, end_utc = _resolve_window(ctx.tz, ctx.now_utc, period, anchor)
        stmt = select(func.count(Appointment.id)).where(
            and_(Appointment.status == "scheduled")
        )
        if start_utc is not None:
            stmt = stmt.where(Appointment.starts_at >= start_utc)
        if end_utc is not None:
            stmt = stmt.where(Appointment.starts_at < end_utc)
        result = await ctx.session.execute(stmt)
        count = int(result.scalar_one() or 0)

        label = _PERIOD_LABELS[period]
        if period == "date" and anchor is not None:
            label = anchor.strftime("%d.%m.%Y")
        text = f"📅 {label.capitalize()}: <b>{count}</b> {_plural_appts(count)}."
        return ActionResponse(result=ActionResult.EXECUTED, text=text)

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError("count_appointments is read-only — execute should not be called")


def _resolve_window(
    tz: Any, now_utc: datetime, period: str, anchor: date | None
) -> tuple[datetime | None, datetime | None]:
    """Match list_appointments' window semantics so counts agree with lists."""
    today_local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz).date()

    if period == "today":
        start = datetime.combine(today_local, time(0), tzinfo=tz)
        end = start + timedelta(days=1)
    elif period == "tomorrow":
        d = today_local + timedelta(days=1)
        start = datetime.combine(d, time(0), tzinfo=tz)
        end = start + timedelta(days=1)
    elif period == "week":
        start = datetime.combine(today_local, time(0), tzinfo=tz)
        end = start + timedelta(days=7)
    elif period == "month":
        first = today_local.replace(day=1)
        nxt = (
            first.replace(year=first.year + 1, month=1)
            if first.month == 12
            else first.replace(month=first.month + 1)
        )
        start = datetime.combine(first, time(0), tzinfo=tz)
        end = datetime.combine(nxt, time(0), tzinfo=tz)
    elif period == "date" and anchor is not None:
        start = datetime.combine(anchor, time(0), tzinfo=tz)
        end = start + timedelta(days=1)
    else:
        # period == "all" — future-only from today 00:00
        start = datetime.combine(today_local, time(0), tzinfo=tz)
        return (start.astimezone(timezone.utc).replace(tzinfo=None), None)

    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )
