"""edit_note — voice/text equivalent of «📝 Заметка»."""

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
    EditableField,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class EditNoteAction:
    name: ClassVar[str] = "edit_note"
    description: ClassVar[str] = (
        "Заменить или добавить заметку к существующей записи. "
        "Используй для команд «добавь к записи Иры заметку френч», "
        "«заметка для Иры завтра: гель»."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "✅ Сохранить"
    cancel_label: ClassVar[str] = "❌ Отменить"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента, чьей записи касается заметка",
            },
            "date": {
                "type": "string",
                "description": "YYYY-MM-DD: дата записи (если уточнили)",
            },
            "time": {
                "type": "string",
                "description": "HH:MM: время записи (если уточнили)",
            },
            "note": {
                "type": "string",
                "description": "Текст заметки (что делаем за визит)",
            },
        },
        "required": ["client_name", "note"],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        name = (args.get("client_name") or "").strip()
        note = (args.get("note") or "").strip()
        client_id_hint = args.get("client_id")
        appointment_id_hint = args.get("appointment_id")

        # Plan #6 Layer A — pick the appointment FIRST when client_name is
        # empty. The note text may also still be empty here; the second-brain
        # question loop handles missing-text via text-input AFTER the user
        # picks an appointment.
        if (
            not name
            and client_id_hint is None
            and appointment_id_hint is None
        ):
            clarify = await _clarify_no_client(ctx, args)
            if clarify is not None:
                return clarify
            # No candidates → fall through to the original FAIL paths below.

        if not note and appointment_id_hint is None:
            return ActionResponse(
                result=ActionResult.FAIL, text="Не понял текст заметки."
            )

        # Resolve client.
        if client_id_hint is None:
            if not name:
                return ActionResponse(result=ActionResult.FAIL, text="Не понял имя клиента.")
            candidates = await resolve_client(ctx.session, name)
            if not candidates:
                return ActionResponse(
                    result=ActionResult.FAIL,
                    text=f"Не нашёл клиента «{html.escape(name)}».",
                )
            if len(candidates) > 1:
                return ActionResponse(
                    result=ActionResult.CLARIFY,
                    text=f"У тебя {len(candidates)} клиента с таким именем — какому пишем заметку?",
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
                    text=f"У {html.escape(client.name)} несколько записей — к какой пишем?",
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

        old_note = appt.visit_note or "—"
        text = (
            "Записать заметку:\n"
            f"<b>{html.escape(client.name)}</b>, {format_local_dt(appt.starts_at, ctx.tz)}\n"
            f"Старая: {html.escape(old_note)}\n"
            f"Новая: {html.escape(note)}"
        )
        return ActionResponse(
            result=ActionResult.CONFIRM,
            text=text,
            pending_payload={"appointment_id": appt.id, "note": note},
            editable_fields=[
                EditableField(
                    key="note",
                    label="Заметка",
                    editor="text_input",
                    prompt_text="Напиши новую заметку:",
                ),
            ],
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        appt_id = int(payload["appointment_id"])
        note = str(payload["note"])
        updated = await AppointmentRepository(ctx.session).update_visit_note(
            appt_id, note
        )
        if updated is None:
            return ActionResponse(result=ActionResult.FAIL, text="Запись не найдена.")
        return ActionResponse(result=ActionResult.EXECUTED, text="✅ Заметка сохранена.")


async def _clarify_no_client(
    ctx: ActionContext, args: dict[str, Any]
) -> ActionResponse | None:
    """Plan #6 Layer A helper. Build a CLARIFY response listing candidate
    appointments when the user said «добавь заметку» (and maybe a date) but
    no client. Returns None if there are no candidates."""
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
        f"На {date_iso} {len(options)} записей — к какой пишем заметку?"
        if date_iso
        else f"Ближайшие записи ({len(options)}) — к какой пишем заметку?"
    )
    return ActionResponse(
        result=ActionResult.CLARIFY,
        text=prompt,
        clarify_options=options,
    )
