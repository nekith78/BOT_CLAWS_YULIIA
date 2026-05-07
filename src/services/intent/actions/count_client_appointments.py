"""count_client_appointments — read-only «сколько записей у Иры» counter."""

from __future__ import annotations

import html
from typing import Any, ClassVar

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
        "Посчитать сколько записей у конкретного клиента (только активных). "
        "Используй для команд «сколько записей у Иры», «сколько визитов у Олега»."
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
        count = len(appts)
        text = (
            f"👤 У <b>{html.escape(client.name)}</b>: "
            f"<b>{count}</b> {_plural_appts(count)} (активных)."
        )
        return ActionResponse(result=ActionResult.EXECUTED, text=text)

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        raise RuntimeError(
            "count_client_appointments is read-only — execute should not be called"
        )
