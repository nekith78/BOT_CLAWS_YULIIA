"""bulk_cancel_by_date — отменить все записи на одну дату.

Защита: на CONFIRM показывается полный список того, что будет отменено
(клиент + время каждой записи). Юзер видит ровно объём изменений до
того как подтвердит.

Идемпотентность: между plan() и execute() запись могла быть отменена
вручную — execute считает реально отменённые ids и не падает на уже-
не-«scheduled» строчках.
"""

from __future__ import annotations

import html
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, ClassVar

from src.services.formatters import format_appointment_line, format_date_ru
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
    EditableField,
)
from src.services.notifications import cancel_for_appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class BulkCancelByDateAction:
    name: ClassVar[str] = "bulk_cancel_by_date"
    description: ClassVar[str] = (
        "Отменить ВСЕ активные записи на одну конкретную дату. Используй "
        "для команд «отмени все записи на завтра», «отмени все записи на "
        "8 мая», «отмени всё на пятницу»."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "✅ Отменить все"
    cancel_label: ClassVar[str] = "⬅️ Назад"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "YYYY-MM-DD — дата, на которую отменяем все записи",
            },
        },
        "required": ["date"],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        date_str = (args.get("date") or "").strip()
        try:
            target = date.fromisoformat(date_str)
        except ValueError:
            return ActionResponse(
                result=ActionResult.FAIL,
                text=f"Не разобрал дату: {html.escape(date_str)}.",
            )

        start_local = datetime.combine(target, time(0), tzinfo=ctx.tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

        repo = AppointmentRepository(ctx.session)
        appts = await repo.list_in_range(
            start=start_utc, end=end_utc, statuses=("scheduled",)
        )

        if not appts:
            return ActionResponse(
                result=ActionResult.FAIL,
                text=f"На {format_date_ru(start_local)} активных записей нет.",
            )

        # Build the safety preview.
        client_repo = ClientRepository(ctx.session)
        lines = [
            f"⚠️ Отменить <b>все {len(appts)} записей</b> на "
            f"{format_date_ru(start_local)}?",
            "",
        ]
        for a in appts:
            c = await client_repo.get(a.client_id)
            if c is None:
                continue
            lines.append(f"  • {format_appointment_line(a, c, tz=ctx.tz)}")
        lines.append("")
        lines.append("Это действие нельзя отменить.")

        return ActionResponse(
            result=ActionResult.CONFIRM,
            text="\n".join(lines),
            pending_payload={
                "date": date_str,
                "appointment_ids": [a.id for a in appts],
            },
            editable_fields=[
                EditableField(key="date", label="Дата", editor="calendar"),
            ],
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        ids: list[int] = list(payload.get("appointment_ids") or [])
        if not ids:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Список записей пустой — нечего отменять.",
            )
        repo = AppointmentRepository(ctx.session)
        cancelled = 0
        for appt_id in ids:
            existing = await repo.get(int(appt_id))
            if existing is None or existing.status != "scheduled":
                continue
            updated = await repo.update_status(int(appt_id), "cancelled")
            if updated is not None:
                cancelled += 1

        # Release SQLite write lock before APScheduler clears its rows.
        await ctx.session.commit()

        for appt_id in ids:
            await cancel_for_appointment(
                ctx.session, scheduler=ctx.scheduler, appointment_id=int(appt_id)
            )

        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=f"✅ Отменено {cancelled} из {len(ids)} записей.",
        )
