"""list_client_history — voice/text equivalent of «История» card.

Read-only: shows scheduled + done visits for a single client, newest first.
"""

from __future__ import annotations

import html
from datetime import timezone
from typing import Any, ClassVar

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import ApptCD
from src.services.formatters import format_appointment_line, format_date_ru
from src.services.intent.actions._common import client_label
from src.services.intent.resolvers import resolve_client
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
    ClarifyOption,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


class ListClientHistoryAction:
    name: ClassVar[str] = "list_client_history"
    description: ClassVar[str] = (
        "Показать историю записей конкретного клиента (прошлые и будущие, "
        "кроме отменённых). Это read-only — ничего не меняет."
    )
    confirm_required: ClassVar[bool] = False
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента, чью историю показать",
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
                    text=f"У тебя {len(candidates)} клиента с таким именем — чью историю?",
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
            client.id, statuses=("scheduled", "done")
        )
        header = f"История · <b>{html.escape(client.name)}</b>"
        if not appts:
            return ActionResponse(
                result=ActionResult.EXECUTED,
                text=f"{header}\n\nЗаписей нет.",
            )

        lines = [header, ""]
        rows: list[list[InlineKeyboardButton]] = []
        # list_for_client returns newest first — keep that order for «история».
        for appt in appts:
            label = format_appointment_line(appt, client, tz=ctx.tz)
            local_date = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(ctx.tz)
            lines.append(f"{format_date_ru(local_date)} · {label}")
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{format_date_ru(local_date)} · {label}",
                        callback_data=ApptCD(
                            action="view", appointment_id=appt.id
                        ).pack(),
                    )
                ]
            )

        return ActionResponse(
            result=ActionResult.EXECUTED,
            text="\n".join(lines),
            keyboard=InlineKeyboardMarkup(inline_keyboard=rows),
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError(
            "list_client_history is read-only — execute should not be called"
        )
