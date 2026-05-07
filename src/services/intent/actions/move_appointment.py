"""move_appointment — voice/text-driven equivalent of «📅 Перенести».

Picks the source appointment by client name + optional current date/time
hints (defaults to the client's nearest future record), then moves it to
the new date/time. New_date and new_time can be partial: missing parts
inherit from the current slot.
"""

from __future__ import annotations

import html
from datetime import date, datetime, time, timezone
from typing import Any, ClassVar

from src.services import settings_service
from src.services.intent.actions._common import client_label, format_local_dt
from src.services.intent.resolvers import resolve_appointment, resolve_client
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
    ClarifyOption,
    EditableField,
)
from src.services.notifications import reschedule_for_appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class MoveAppointmentAction:
    name: ClassVar[str] = "move_appointment"
    description: ClassVar[str] = (
        "Перенести существующую запись клиента на другую дату/время. "
        "Используй для команд «перенеси Иру на 16 мая», «перенеси с 14:30 "
        "на 16:00», «перенеси запись Иры на завтра в 11:00»."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "✅ Перенести"
    cancel_label: ClassVar[str] = "❌ Отменить"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента, чью запись переносим",
            },
            "current_date": {
                "type": "string",
                "description": "YYYY-MM-DD: дата текущей записи (если уточнили)",
            },
            "current_time": {
                "type": "string",
                "description": "HH:MM: время текущей записи (если уточнили)",
            },
            "new_date": {
                "type": "string",
                "description": "YYYY-MM-DD: куда переносим (если не задано — тот же день)",
            },
            "new_time": {
                "type": "string",
                "description": "HH:MM: куда переносим (если не задано — то же время)",
            },
        },
        "required": ["client_name"],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        name = (args.get("client_name") or "").strip()
        client_id_hint = args.get("client_id")
        appointment_id_hint = args.get("appointment_id")
        new_date = args.get("new_date") or None
        new_time = args.get("new_time") or None

        if not new_date and not new_time:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Не понял, на когда переносим — повтори с датой и/или временем.",
            )

        # 1. Resolve client.
        if client_id_hint is None:
            if not name:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text="Не понял имя клиента — повтори.",
                )
            candidates = await resolve_client(ctx.session, name)
            if not candidates:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text=f"Не нашёл клиента с именем «{html.escape(name)}».",
                )
            if len(candidates) > 1:
                return ActionResponse(
                    result=ActionResult.CLARIFY,
                    text=f"У тебя {len(candidates)} клиента с таким именем — кого переносим?",
                    clarify_options=[
                        ClarifyOption(
                            label=client_label(c.name, c.instagram, idx),
                            payload={"client_id": c.id},
                        )
                        for idx, c in enumerate(candidates)
                    ],
                )
            client = candidates[0]
        else:
            fetched_client = await ClientRepository(ctx.session).get(
                int(client_id_hint)
            )
            if fetched_client is None:
                return ActionResponse(
                    result=ActionResult.FAIL, text="Клиент не найден."
                )
            client = fetched_client

        # 2. Resolve source appointment.
        if appointment_id_hint is None:
            appts = await resolve_appointment(
                ctx.session,
                client_id=client.id,
                tz=ctx.tz,
                date_hint=args.get("current_date"),
                time_hint=args.get("current_time"),
                now_utc=ctx.now_utc,
            )
            if not appts:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text=f"У {html.escape(client.name)} нет подходящей записи.",
                )
            if len(appts) > 1:
                return ActionResponse(
                    result=ActionResult.CLARIFY,
                    text=f"У {html.escape(client.name)} несколько записей — какую переносим?",
                    clarify_options=[
                        ClarifyOption(
                            label=format_local_dt(a.starts_at, ctx.tz),
                            payload={"appointment_id": a.id},
                        )
                        for a in appts
                    ],
                )
            appt = appts[0]
        else:
            fetched_appt = await AppointmentRepository(ctx.session).get(
                int(appointment_id_hint)
            )
            if fetched_appt is None or fetched_appt.status != "scheduled":
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text="Запись не найдена или уже не активна.",
                )
            appt = fetched_appt

        # 3. Compute new starts_at — partials inherit from the source slot.
        current_local = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(ctx.tz)
        try:
            new_local_date = (
                date.fromisoformat(new_date) if new_date else current_local.date()
            )
            new_local_time = (
                _parse_hhmm(new_time) if new_time else current_local.time().replace(microsecond=0)
            )
        except ValueError:
            return ActionResponse(
                result=ActionResult.FAIL, text="Не разобрал новую дату или время."
            )
        new_starts_local = datetime.combine(new_local_date, new_local_time, tzinfo=ctx.tz)
        new_starts_utc = new_starts_local.astimezone(timezone.utc).replace(tzinfo=None)

        if new_starts_utc <= ctx.now_utc:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Новая дата/время уже в прошлом.",
            )
        if new_starts_utc == appt.starts_at:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Это то же самое время — переносить нечего.",
            )

        # 4. Overlap check (exclude this appointment itself).
        duration = await settings_service.get_default_duration_min(ctx.session)
        overlap = await AppointmentRepository(ctx.session).find_overlap(
            starts_at=new_starts_utc, duration_min=duration, exclude_id=appt.id
        )
        if overlap:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="⚠️ В это время уже есть другая запись.",
            )

        text = (
            "Перенести запись:\n"
            f"<b>{html.escape(client.name)}</b>\n"
            f"с {format_local_dt(appt.starts_at, ctx.tz)}\n"
            f"на {format_local_dt(new_starts_utc, ctx.tz)}"
        )
        payload = {
            "appointment_id": appt.id,
            "new_starts_at_utc_iso": new_starts_utc.isoformat(),
        }
        return ActionResponse(
            result=ActionResult.CONFIRM,
            text=text,
            pending_payload=payload,
            editable_fields=[
                EditableField(key="new_date", label="Новая дата", editor="calendar"),
                EditableField(key="new_time", label="Новое время", editor="time_picker"),
            ],
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        appt_id = int(payload["appointment_id"])
        new_starts_at = datetime.fromisoformat(payload["new_starts_at_utc_iso"])

        repo = AppointmentRepository(ctx.session)
        existing = await repo.get(appt_id)
        if existing is None or existing.status != "scheduled":
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Запись пропала или уже не активна.",
            )

        duration = await settings_service.get_default_duration_min(ctx.session)
        # Re-check overlap right before write — another booking could've landed.
        overlap = await repo.find_overlap(
            starts_at=new_starts_at, duration_min=duration, exclude_id=appt_id
        )
        if overlap:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="⚠️ В это время уже занято — перенос отменён.",
            )

        rescheduled = await repo.reschedule(
            appt_id, starts_at=new_starts_at, duration_min=duration
        )
        if rescheduled is None:
            return ActionResponse(
                result=ActionResult.FAIL, text="Запись не найдена."
            )

        # Release the SQLite write lock before APScheduler writes apscheduler_jobs.
        await ctx.session.commit()

        await reschedule_for_appointment(
            ctx.session,
            scheduler=ctx.scheduler,
            appointment_id=appt_id,
            job_runner=ctx.notify_runner,
        )

        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=f"✅ Перенесено на {format_local_dt(new_starts_at, ctx.tz)}.",
        )


def _parse_hhmm(value: str) -> time:
    hh_s, mm_s = value.split(":")
    return time(int(hh_s), int(mm_s))
