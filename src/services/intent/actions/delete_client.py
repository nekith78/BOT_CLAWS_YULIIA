"""delete_client — voice/text equivalent of «🗑 Удалить клиента»."""

from __future__ import annotations

import html
from typing import Any, ClassVar

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


class DeleteClientAction:
    name: ClassVar[str] = "delete_client"
    description: ClassVar[str] = (
        "Удалить клиента со всеми его записями. Деструктивная операция — "
        "перед фактическим удалением требует явного подтверждения."
    )
    confirm_required: ClassVar[bool] = True
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "client_name": {
                "type": "string",
                "description": "Имя клиента для удаления",
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
                    text=f"У тебя {len(candidates)} клиента с таким именем — какого удалить?",
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
        n_appts = len(appts)
        appts_line = (
            f"\n⚠️ У клиента {n_appts} активных/прошлых записей — они тоже удалятся."
            if n_appts > 0
            else ""
        )

        text = (
            "🗑 <b>Удалить клиента?</b>\n"
            f"<b>{html.escape(client.name)}</b>"
            + (f" (@{html.escape(client.instagram)})" if client.instagram else "")
            + appts_line
            + "\n\nЭто нельзя отменить."
        )
        return ActionResponse(
            result=ActionResult.CONFIRM,
            text=text,
            pending_payload={"client_id": client.id},
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        client_id = int(payload["client_id"])
        deleted = await ClientRepository(ctx.session).delete(client_id)
        if not deleted:
            return ActionResponse(result=ActionResult.FAIL, text="Клиент уже удалён.")
        return ActionResponse(result=ActionResult.EXECUTED, text="✅ Клиент удалён.")
