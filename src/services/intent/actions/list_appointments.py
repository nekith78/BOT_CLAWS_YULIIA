"""list_appointments — read-only equivalent of «📋 Записи» button.

Voice/text command «покажи записи на сегодня / на этой неделе / на 8
мая» lands here. Result is the same period header + tappable list of
appointment buttons that the menu produces.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, ClassVar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ApptCD
from src.services.formatters import (
    format_appointment_line,
    format_date_ru,
    format_period_header,
    group_by_day,
)
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
)
from src.storage.models import Appointment, Client
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

_VALID_PERIODS = {"today", "tomorrow", "week", "month", "all", "date"}


class ListAppointmentsAction:
    name: ClassVar[str] = "list_appointments"
    description: ClassVar[str] = (
        "Показать список записей за период: сегодня, завтра, неделя, "
        "месяц, все будущие, или конкретная дата. Это read-only — "
        "ничего не меняет в БД."
    )
    confirm_required: ClassVar[bool] = False
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
        if period not in _VALID_PERIODS:
            return ActionResponse(
                result=ActionResult.FAIL,
                text=f"Не понял период: {period!r}.",
            )

        anchor: date | None = None
        if period == "date":
            date_str = args.get("date") or ""
            try:
                anchor = date.fromisoformat(date_str)
            except ValueError:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text="Не разобрал дату. Формат: YYYY-MM-DD.",
                )

        text, keyboard = await _build_payload(
            ctx, period=period, anchor=anchor
        )
        return ActionResponse(
            result=ActionResult.EXECUTED, text=text, keyboard=keyboard
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        # Read-only — confirm_required=False means execute is never called.
        raise RuntimeError("list_appointments is read-only — execute should not be called")


async def _build_payload(
    ctx: ActionContext, *, period: str, anchor: date | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    today_local = ctx.now_utc.replace(tzinfo=timezone.utc).astimezone(ctx.tz).date()

    start_local: datetime | None = None
    end_local: datetime | None = None
    header_anchor = today_local

    if period == "today":
        start_local = datetime.combine(today_local, time(0), tzinfo=ctx.tz)
        end_local = start_local + timedelta(days=1)
    elif period == "tomorrow":
        tomorrow = today_local + timedelta(days=1)
        start_local = datetime.combine(tomorrow, time(0), tzinfo=ctx.tz)
        end_local = start_local + timedelta(days=1)
        header_anchor = tomorrow
    elif period == "week":
        start_local = datetime.combine(today_local, time(0), tzinfo=ctx.tz)
        end_local = start_local + timedelta(days=7)
    elif period == "month":
        month_first = today_local.replace(day=1)
        start_local = datetime.combine(month_first, time(0), tzinfo=ctx.tz)
        next_month = (
            month_first.replace(year=month_first.year + 1, month=1)
            if month_first.month == 12
            else month_first.replace(month=month_first.month + 1)
        )
        end_local = datetime.combine(next_month, time(0), tzinfo=ctx.tz)
        header_anchor = month_first
    elif period == "date" and anchor is not None:
        start_local = datetime.combine(anchor, time(0), tzinfo=ctx.tz)
        end_local = start_local + timedelta(days=1)
        header_anchor = anchor
    # period == "all" → no window; future-only

    repo = AppointmentRepository(ctx.session)
    if start_local is not None and end_local is not None:
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        appts = await repo.list_in_range(start=start_utc, end=end_utc)
    else:
        # `all` — future-only from today 00:00 local.
        today_start_utc = (
            datetime.combine(today_local, time(0), tzinfo=ctx.tz)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )
        appts = await repo.list_in_range(
            start=today_start_utc, end=datetime(2100, 1, 1)
        )

    pairs = await _hydrate(ctx.session, appts)

    header = (
        "Все будущие записи"
        if period == "all"
        else format_period_header(
            period, anchor=datetime.combine(header_anchor, time(0))
        )
    )
    if not pairs:
        return f"{header}\n\nЗаписей нет.", None

    rows: list[list[InlineKeyboardButton]] = []
    if period in {"today", "tomorrow", "date"}:
        for appt, client in pairs:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=format_appointment_line(appt, client, tz=ctx.tz),
                        callback_data=ApptCD(
                            action="view", appointment_id=appt.id
                        ).pack(),
                    )
                ]
            )
        return header, InlineKeyboardMarkup(inline_keyboard=rows)

    # Multi-day grouping (week/month/all).
    grouped = group_by_day(pairs, tz=ctx.tz)
    lines: list[str] = [header, ""]
    for day, items in grouped.items():
        lines.append(format_date_ru(datetime.combine(day, time(0))))
        for appt, client in items:
            label = format_appointment_line(appt, client, tz=ctx.tz)
            lines.append(label)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=ApptCD(
                            action="view", appointment_id=appt.id
                        ).pack(),
                    )
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip(), InlineKeyboardMarkup(inline_keyboard=rows)


async def _hydrate(
    session: Any, appts: list[Appointment]
) -> list[tuple[Appointment, Client]]:
    if not appts:
        return []
    repo = ClientRepository(session)
    pairs: list[tuple[Appointment, Client]] = []
    for appt in appts:
        client = await repo.get(appt.client_id)
        if client is not None:
            pairs.append((appt, client))
    return pairs
