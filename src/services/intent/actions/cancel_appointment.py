"""cancel_appointment — voice/text equivalent of «❌ Отменить запись»."""

from __future__ import annotations

import html
from datetime import date as _date
from typing import Any, ClassVar

from src.services.intent.actions._common import (
    client_label,
    format_local_dt,
    format_local_time,
)
from src.services.intent.resolvers import resolve_appointment, resolve_client
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
    ClarifyOption,
)
from src.services.notifications import cancel_for_appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class CancelAppointmentAction:
    name: ClassVar[str] = "cancel_appointment"
    description: ClassVar[str] = (
        "Отменить запись клиента. Используй для команд «отмени запись Иры», "
        "«отмени Иру на завтра», «отмени запись на 16 мая в 14:00»."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "✅ Отменить запись"
    cancel_label: ClassVar[str] = "⬅️ Назад"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента, чью запись отменяем",
            },
            "date": {
                "type": "string",
                "description": "YYYY-MM-DD: дата записи (если уточнили)",
            },
            "time": {
                "type": "string",
                "description": "HH:MM: время записи (если уточнили)",
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

        # Resolve client.
        if client_id_hint is None:
            if not name:
                # Plan #6 Layer A — «отмени запись» / «отмени запись на ДАТУ»
                # without a client name. Instead of refusing, show the user a
                # list of candidate appointments and let them pick one.
                clarify = await _clarify_no_client(ctx, args)
                if clarify is not None:
                    return clarify
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text="На эту дату записей нет.",
                ) if args.get("date") else ActionResponse(
                    result=ActionResult.FAIL,
                    text="Нет ни одной активной записи.",
                )
            candidates = await resolve_client(ctx.session, name)
            if not candidates:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text=f"Не нашёл клиента «{html.escape(name)}».",
                )
            if len(candidates) > 1:
                return ActionResponse(
                    result=ActionResult.CLARIFY,
                    text=f"У тебя {len(candidates)} клиента с таким именем — кого отменяем?",
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
            fetched = await ClientRepository(ctx.session).get(int(client_id_hint))
            if fetched is None:
                return ActionResponse(result=ActionResult.FAIL, text="Клиент не найден.")
            client = fetched

        # Resolve appointment.
        if appointment_id_hint is None:
            appts = await resolve_appointment(
                ctx.session,
                client_id=client.id,
                tz=ctx.tz,
                date_hint=args.get("date"),
                time_hint=args.get("time"),
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
                    text=f"У {html.escape(client.name)} несколько записей — какую отменить?",
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

        text = (
            "Отменить запись:\n"
            f"<b>{html.escape(client.name)}</b>\n"
            f"📅 {format_local_dt(appt.starts_at, ctx.tz)}"
        )
        return ActionResponse(
            result=ActionResult.CONFIRM,
            text=text,
            pending_payload={"appointment_id": appt.id},
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        appt_id = int(payload["appointment_id"])
        repo = AppointmentRepository(ctx.session)
        existing = await repo.get(appt_id)
        if existing is None or existing.status != "scheduled":
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Запись пропала или уже отменена.",
            )

        updated = await repo.update_status(appt_id, "cancelled")
        if updated is None:
            return ActionResponse(result=ActionResult.FAIL, text="Запись не найдена.")

        # Release the SQLite write lock before APScheduler removes its row.
        await ctx.session.commit()

        await cancel_for_appointment(
            ctx.session, scheduler=ctx.scheduler, appointment_id=appt_id
        )

        return ActionResponse(result=ActionResult.EXECUTED, text="✅ Отменено.")


async def _clarify_no_client(
    ctx: ActionContext, args: dict[str, Any]
) -> ActionResponse | None:
    """Plan #6 Layer A helper. Build a CLARIFY response listing candidate
    appointments when the user said «отмени запись» (and maybe a date) but
    no client. Returns None if there are no candidates — caller emits FAIL."""
    appt_repo = AppointmentRepository(ctx.session)
    date_iso = (args.get("date") or "").strip()
    if date_iso:
        try:
            local_date = _date.fromisoformat(date_iso)
        except ValueError:
            return None
        appts = await appt_repo.list_for_date(local_date, tz=ctx.tz)
    else:
        appts = await appt_repo.list_upcoming(now=ctx.now_utc, limit=10)

    if not appts:
        return None

    # Resolve client names for label rendering. Single fetch loop — client
    # lists are small in this bot.
    client_repo = ClientRepository(ctx.session)
    options: list[ClarifyOption] = []
    for a in appts:
        client = await client_repo.get(a.client_id)
        client_name = client.name if client else "?"
        if date_iso:
            label = f"{client_name} — {format_local_time(a.starts_at, ctx.tz)}"
        else:
            label = f"{client_name} — {format_local_dt(a.starts_at, ctx.tz)}"
        options.append(
            ClarifyOption(
                label=label,
                payload={"appointment_id": a.id, "client_id": a.client_id},
            )
        )

    prompt = (
        f"На {date_iso} {len(options)} записей — какую отменить?"
        if date_iso
        else f"Ближайшие записи ({len(options)}) — какую отменить?"
    )
    return ActionResponse(
        result=ActionResult.CLARIFY,
        text=prompt,
        clarify_options=options,
    )
