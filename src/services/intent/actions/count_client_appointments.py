"""count_client_appointments — «сколько записей у Иры» — counter + tappable list."""

from __future__ import annotations

import html
from datetime import timezone
from typing import Any, ClassVar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ApptCD
from src.services.formatters import format_appointment_line, format_date_ru
from src.services.intent.actions._common import client_label
from src.services.intent.actions.count_appointments import _plural_appts
from src.services.intent.resolvers import resolve_client
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
    ClarifyOption,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class CountClientAppointmentsAction:
    name: ClassVar[str] = "count_client_appointments"
    description: ClassVar[str] = (
        "Показать сколько активных записей у конкретного клиента и список "
        "их (только будущие, status=scheduled). Используй для команд "
        "«сколько записей у Иры», «сколько визитов у Олега»."
    )
    confirm_required: ClassVar[bool] = False
    confirm_label: ClassVar[str] = "✅ Сохранить"
    cancel_label: ClassVar[str] = "❌ Отменить"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента, по которому считаем записи",
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
                    text=f"У тебя {len(candidates)} клиента с таким именем — про какого считаем?",
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

        appts = await AppointmentRepository(ctx.session).list_for_client(
            client.id, statuses=("scheduled",)
        )
        # Future-only — past «scheduled» rows are leftovers.
        appts = [a for a in appts if a.starts_at >= ctx.now_utc]
        appts.sort(key=lambda a: a.starts_at)
        count = len(appts)

        if count == 0:
            return ActionResponse(
                result=ActionResult.EXECUTED,
                text=f"👤 У <b>{html.escape(client.name)}</b> нет активных записей.",
            )

        rows: list[list[InlineKeyboardButton]] = []
        snapshot_items: list[dict[str, Any]] = []
        for a in appts:
            local_dt = a.starts_at.replace(tzinfo=timezone.utc).astimezone(ctx.tz)
            label = (
                f"{format_date_ru(local_dt)} · "
                f"{format_appointment_line(a, client, tz=ctx.tz)}"
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=ApptCD(
                            action="view", appointment_id=a.id
                        ).pack(),
                    )
                ]
            )
            snapshot_items.append(
                {
                    "client_name": client.name,
                    "date": local_dt.date().isoformat(),
                    "time": local_dt.strftime("%H:%M"),
                    "note": a.visit_note,
                }
            )

        text = (
            f"👤 У <b>{html.escape(client.name)}</b>: "
            f"<b>{count}</b> {_plural_appts(count)} (активных). "
            "Тапни чтобы открыть:"
        )
        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=text,
            keyboard=InlineKeyboardMarkup(inline_keyboard=rows),
            context_snapshot={
                "client_name": client.name,
                "appointments": snapshot_items,
            },
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError(
            "count_client_appointments is read-only — execute should not be called"
        )
