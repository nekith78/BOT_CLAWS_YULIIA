"""bulk_cancel_by_client — отменить все будущие записи одного клиента.

Защита: preview со списком записей в CONFIRM. Disambiguation по имени
если клиентов несколько (как в обычных action'ах).
"""

from __future__ import annotations

import html
from datetime import timezone
from typing import Any, ClassVar

from src.services.formatters import format_appointment_line, format_date_ru
from src.services.intent.actions._common import client_label
from src.services.intent.resolvers import resolve_client
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
    ClarifyOption,
)
from src.services.notifications import cancel_for_appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class BulkCancelByClientAction:
    name: ClassVar[str] = "bulk_cancel_by_client"
    description: ClassVar[str] = (
        "Отменить ВСЕ будущие активные записи одного клиента. Используй "
        "для команд «отмени все записи Иры», «отмени всё у Олега»."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "✅ Отменить все"
    cancel_label: ClassVar[str] = "⬅️ Назад"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента, чьи записи отменяем оптом",
            },
        },
        "required": ["client_name"],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        name = (args.get("client_name") or "").strip()
        client_id_hint = args.get("client_id")

        if client_id_hint is None:
            if not name:
                return ActionResponse(
                    result=ActionResult.FAIL, text="Не понял имя клиента."
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
                    text=f"У тебя {len(candidates)} клиента с таким именем — у кого отменяем всё?",
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

        repo = AppointmentRepository(ctx.session)
        appts = await repo.list_for_client(client.id, statuses=("scheduled",))
        # Future-only.
        appts = [a for a in appts if a.starts_at >= ctx.now_utc]

        if not appts:
            return ActionResponse(
                result=ActionResult.FAIL,
                text=f"У {html.escape(client.name)} нет будущих активных записей.",
            )

        lines = [
            f"⚠️ Отменить <b>все {len(appts)} будущих записей</b> у "
            f"<b>{html.escape(client.name)}</b>?",
            "",
        ]
        for a in sorted(appts, key=lambda x: x.starts_at):
            local_dt = a.starts_at.replace(tzinfo=timezone.utc).astimezone(ctx.tz)
            lines.append(
                f"  • {format_date_ru(local_dt)} · "
                f"{format_appointment_line(a, client, tz=ctx.tz)}"
            )
        lines.append("")
        lines.append("Это действие нельзя отменить.")

        return ActionResponse(
            result=ActionResult.CONFIRM,
            text="\n".join(lines),
            pending_payload={
                "client_id": client.id,
                "appointment_ids": [a.id for a in appts],
            },
            # No editable_fields — to change which client, user cancels and re-issues.
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

        await ctx.session.commit()

        for appt_id in ids:
            await cancel_for_appointment(
                ctx.session, scheduler=ctx.scheduler, appointment_id=int(appt_id)
            )

        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=f"✅ Отменено {cancelled} из {len(ids)} записей.",
        )
