"""bulk_delete_clients — удалить ВСЕХ клиентов и ВСЕ их записи.

Действие необратимое и широкое — поэтому защита трёхслойная:
1. CONFIRM-card показывает количество клиентов и количество записей
   которые исчезнут вместе с ними (cascade FK).
2. Текст содержит явное «ЭТО НЕЛЬЗЯ ОТМЕНИТЬ» в верхнем регистре.
3. Confirm-кнопка переименована в «🗑 Удалить ВСЕХ» — никакой нейтральной
   формулировки типа «Сохранить».
4. Если в БД >0 клиентов — execute снимает все APScheduler-jobs и
   проводит cascade delete; иначе FAIL без действий.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from sqlalchemy import func, select

from src.services.intent.actions.count_appointments import _plural_appts
from src.services.intent.actions.count_clients import _plural_clients
from src.services.intent.types import (
    ActionContext,
    ActionResponse,
    ActionResult,
)
from src.services.notifications import cancel_for_appointment
from src.storage.models import Appointment, Client
from src.storage.repositories.clients import ClientRepository

log = logging.getLogger(__name__)


class BulkDeleteClientsAction:
    name: ClassVar[str] = "bulk_delete_clients"
    description: ClassVar[str] = (
        "ОПАСНО: удалить ВСЕХ клиентов из базы (со всеми их записями). "
        "Используй ТОЛЬКО когда пользователь явно сказал «удали всех клиентов», "
        "«очисти базу», «сотри всё». Если есть малейшая двусмысленность — "
        "не вызывай эту tool."
    )
    confirm_required: ClassVar[bool] = True
    confirm_label: ClassVar[str] = "🗑 Удалить ВСЕХ"
    cancel_label: ClassVar[str] = "⬅️ Не удалять"
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        clients_count_result = await ctx.session.execute(select(func.count(Client.id)))
        n_clients = int(clients_count_result.scalar_one() or 0)
        if n_clients == 0:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="В базе нет клиентов — удалять нечего.",
            )

        appts_count_result = await ctx.session.execute(
            select(func.count(Appointment.id))
        )
        n_appts = int(appts_count_result.scalar_one() or 0)

        text = (
            "🛑 <b>ОПАСНО: удалить ВСЕХ клиентов?</b>\n\n"
            f"Будет удалено: <b>{n_clients}</b> {_plural_clients(n_clients)} "
            f"и <b>{n_appts}</b> {_plural_appts(n_appts)} вместе с ними.\n\n"
            "ЭТО НЕЛЬЗЯ ОТМЕНИТЬ. Запиши важные данные заранее, если нужно."
        )

        return ActionResponse(
            result=ActionResult.CONFIRM,
            text=text,
            pending_payload={"expected_clients": n_clients},
        )

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        client_repo = ClientRepository(ctx.session)

        # Re-count to detect race (someone already deleted between plan + execute).
        result = await ctx.session.execute(select(func.count(Client.id)))
        actual_clients = int(result.scalar_one() or 0)
        if actual_clients == 0:
            return ActionResponse(
                result=ActionResult.FAIL,
                text="Клиентов уже нет — никаких изменений.",
            )

        # Collect all appointment ids first so we can clear their notifications
        # AFTER the cascade delete. (Cascading happens via the FK — appointments
        # rows go away when their client is deleted.)
        result = await ctx.session.execute(select(Appointment.id))
        appt_ids = [int(row[0]) for row in result.all()]

        result = await ctx.session.execute(select(Client.id))
        client_ids = [int(row[0]) for row in result.all()]

        deleted = 0
        for cid in client_ids:
            ok = await client_repo.delete(cid)
            if ok:
                deleted += 1

        await ctx.session.commit()

        # Tell APScheduler to drop jobs for every (now-gone) appointment.
        # cancel_for_appointment is best-effort: appt rows have already
        # been cascade-deleted, so any failure to find them is benign and
        # logged at debug level.
        for appt_id in appt_ids:
            try:
                await cancel_for_appointment(
                    ctx.session, scheduler=ctx.scheduler, appointment_id=appt_id
                )
            except Exception as exc:
                log.debug(
                    "bulk_delete: cancel_for_appointment(%s) failed: %s",
                    appt_id, exc,
                )

        return ActionResponse(
            result=ActionResult.EXECUTED,
            text=f"🗑 Удалено {deleted} клиентов. База очищена.",
        )
