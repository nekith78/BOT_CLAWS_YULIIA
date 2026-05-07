"""create_appointment — voice/text-driven equivalent of «+ Запись» wizard.

The LLM gets a tool with this action's schema; on fire, the action's
`plan()` validates args, resolves the client (or proposes creating a new
one), checks for time-slot overlap, and returns a CONFIRM card.
`execute()` runs after the user taps ✅.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, ClassVar

from src.services import settings_service
from src.services.intent.actions._common import (
    client_label,
    format_local_dt,
    parse_local_to_utc,
)
from src.services.intent.resolvers import resolve_client
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


class CreateAppointmentAction:
    name: ClassVar[str] = "create_appointment"
    description: ClassVar[str] = (
        "Создать новую запись клиенту. Используй для команд "
        "«запиши Иру на завтра в 14:30», «запиши клиента Х на 8 мая в 11:00»."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "✅ Сохранить"
    cancel_label: ClassVar[str] = "❌ Отменить"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента (как сказал пользователь)",
            },
            "date": {
                "type": "string",
                "description": "Дата записи в формате YYYY-MM-DD",
            },
            "time": {
                "type": "string",
                "description": "Время записи в формате HH:MM (24-часовой)",
            },
            "note": {
                "type": "string",
                "description": "Заметка к визиту (что делаем) — опционально",
            },
            "instagram": {
                "type": "string",
                "description": "Instagram username нового клиента — опционально",
            },
        },
        "required": ["client_name", "date", "time"],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        name = (args.get("client_name") or "").strip()
        date_str = args.get("date") or ""
        time_str = args.get("time") or ""
        note = (args.get("note") or "").strip() or None
        instagram = (args.get("instagram") or "").strip() or None
        client_id_hint = args.get("client_id")  # set after CLARIFY round

        if not name and client_id_hint is None:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Не понял имя клиента — повтори или сделай вручную.",
            )
        if not date_str or not time_str:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Не понял дату или время — повтори или сделай вручную.",
            )

        try:
            starts_at_utc = parse_local_to_utc(date_str, time_str, ctx.tz)
        except ValueError:
            return ActionResponse(
                result=ActionResult.FAIL,
                text=f"Не разобрал дату/время: {html.escape(date_str)} {html.escape(time_str)}",
            )

        if starts_at_utc <= ctx.now_utc:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Эта дата/время уже в прошлом.",
            )

        # Resolve client (or skip if disambiguation already happened).
        if client_id_hint is not None:
            client = await ClientRepository(ctx.session).get(int(client_id_hint))
            if client is None:
                return ActionResponse(
                    result=ActionResult.FAIL, text="Клиент не найден."
                )
            preview_label = html.escape(client.name)
        else:
            candidates = await resolve_client(ctx.session, name)
            if len(candidates) > 1:
                options = [
                    ClarifyOption(
                        label=client_label(c.name, c.instagram, idx),
                        payload={"client_id": c.id},
                    )
                    for idx, c in enumerate(candidates)
                ]
                return ActionResponse(
                    result=ActionResult.CLARIFY,
                    text=f"Нашёл {len(candidates)} клиентов с таким именем — какого записать?",
                    clarify_options=options,
                )
            if len(candidates) == 1:
                client_id_hint = candidates[0].id
                preview_label = html.escape(candidates[0].name)
            else:
                # No match — confirm card will spell out that we'll create a new client.
                client_id_hint = None
                preview_label = f"новый клиент «{html.escape(name)}»"

        # Overlap check (existing-client only — new clients have no past schedule).
        if client_id_hint is not None:
            duration = await settings_service.get_default_duration_min(ctx.session)
            overlap = await AppointmentRepository(ctx.session).find_overlap(
                starts_at=starts_at_utc, duration_min=duration
            )
            if overlap:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text="⚠️ В это время уже есть другая запись.",
                )

        text = (
            "Создать запись:\n"
            f"<b>{preview_label}</b>\n"
            f"📅 {format_local_dt(starts_at_utc, ctx.tz)}"
        )
        if note:
            text += f"\n📝 {html.escape(note)}"

        payload = {
            "client_id": client_id_hint,
            "client_name": name,
            "instagram": instagram,
            "starts_at_utc_iso": starts_at_utc.isoformat(),
            "note": note,
        }
        return ActionResponse(
            result=ActionResult.CONFIRM,
            text=text,
            pending_payload=payload,
            editable_fields=[
                EditableField(
                    key="client_name",
                    label="Имя клиента",
                    editor="text_input",
                    prompt_text="Напиши имя клиента:",
                ),
                EditableField(key="date", label="Дата", editor="calendar"),
                EditableField(key="time", label="Время", editor="time_picker"),
                EditableField(
                    key="note",
                    label="Заметка",
                    editor="text_input",
                    prompt_text="Напиши заметку:",
                ),
                EditableField(
                    key="instagram",
                    label="Instagram",
                    editor="text_input",
                    prompt_text="Напиши Instagram-ник (без @):",
                ),
            ],
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        client_id = payload.get("client_id")
        if client_id is None:
            new_client = await ClientRepository(ctx.session).create(
                name=payload["client_name"],
                instagram=payload.get("instagram"),
            )
            client_id = new_client.id

        starts_at_utc = datetime.fromisoformat(payload["starts_at_utc_iso"])
        duration = await settings_service.get_default_duration_min(ctx.session)

        appt = await AppointmentRepository(ctx.session).create(
            client_id=int(client_id),
            starts_at=starts_at_utc,
            duration_min=duration,
            visit_note=payload.get("note"),
        )

        # Release the SQLite write lock before APScheduler tries to insert
        # its own row (apscheduler_jobs lives in the same DB file).
        await ctx.session.commit()

        await reschedule_for_appointment(
            ctx.session,
            scheduler=ctx.scheduler,
            appointment_id=appt.id,
            job_runner=ctx.notify_runner,
        )

        return ActionResponse(
            result=ActionResult.EXECUTED,
            text="✅ Запись сохранена.",
        )
