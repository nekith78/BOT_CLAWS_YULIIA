"""TEMPORARY debug panel for the notifications stack.

Three slash commands the owner can run from Telegram to verify the
notification pipeline without waiting for real-world fire times:

    /dev_ping_now              — fire a fake offset-ping for the most recent
                                 scheduled appointment, immediately. Bypasses
                                 APScheduler — exercises only senders + HTML.

    /dev_digest_now            — send the eve-digest for tomorrow, immediately.
                                 Bypasses APScheduler.

    /dev_test_after <minutes>  — take the nearest future scheduled appointment,
                                 replace its rules with one that fires in
                                 <minutes> minutes from now, and reschedule.
                                 Exercises the full cycle (queue → fire →
                                 send → mark_sent).

DELETE THIS FILE plus its include_router line in main.py to remove
the panel. Nothing else touches it.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any, cast

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.services import settings_service
from src.services.notifications import reschedule_for_appointment
from src.services.notifications.senders import (
    send_eve_digest,
    send_offset_ping,
)
from src.storage.db import session_scope
from src.storage.models import Appointment
from src.storage.repositories.appointment_notify_overrides import (
    AppointmentNotifyOverrideRepository,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

log = logging.getLogger(__name__)
router = Router(name="dev_panel")


@router.message(Command("dev_ping_now"))
async def handle_ping_now(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        # Most recent scheduled appointment in the future, or last by id if none.
        result = await session.execute(
            select(Appointment)
            .where(Appointment.status == "scheduled", Appointment.starts_at >= now_utc)
            .order_by(Appointment.starts_at)
            .limit(1)
        )
        appt = result.scalar_one_or_none()
        if appt is None:
            result = await session.execute(
                select(Appointment).order_by(desc(Appointment.id)).limit(1)
            )
            appt = result.scalar_one_or_none()
        if appt is None:
            await bot.send_message(
                chat_id=message.chat.id,
                text="🚧 dev: ни одной записи в БД — нечего пинговать.",
            )
            return
        client = await ClientRepository(session).get(appt.client_id)
    if client is None:
        await bot.send_message(
            chat_id=message.chat.id, text="🚧 dev: у записи нет клиента."
        )
        return
    await send_offset_ping(bot, message.chat.id, appt, client, tz=tz, late=False)


@router.message(Command("dev_digest_now"))
async def handle_digest_now(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        today_local = datetime.now(tz=tz).date()
        tomorrow = today_local + timedelta(days=1)
        start_local = datetime.combine(tomorrow, time(0), tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        repo = AppointmentRepository(session)
        appts = await repo.list_in_range(start=start_utc, end=end_utc)
        client_repo = ClientRepository(session)
        pairs = []
        for a in appts:
            c = await client_repo.get(a.client_id)
            if c is not None:
                pairs.append((a, c))
    await send_eve_digest(bot, message.chat.id, pairs, tz=tz, late=False)


@router.message(Command("dev_test_after"))
async def handle_test_after(
    message: Message,
    command: CommandObject,
    bot: Bot,
    **data: Any,
) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    args = (command.args or "").strip()
    try:
        minutes = int(args)
        if minutes < 1:
            raise ValueError
    except ValueError:
        await bot.send_message(
            chat_id=message.chat.id,
            text="🚧 dev: формат — <code>/dev_test_after &lt;минут&gt;</code>.",
        )
        return

    async with session_scope(factory) as session:
        now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        # Nearest future scheduled appointment.
        result = await session.execute(
            select(Appointment)
            .where(Appointment.status == "scheduled", Appointment.starts_at >= now_utc)
            .order_by(Appointment.starts_at)
            .limit(1)
        )
        appt = result.scalar_one_or_none()
        if appt is None:
            await bot.send_message(
                chat_id=message.chat.id,
                text="🚧 dev: нет будущих записей.",
            )
            return
        appointment_id = appt.id
        starts_at_utc = appt.starts_at
        # We want fire_at = now + minutes (independent of how far the
        # appointment is). offset_before is computed relative to the
        # appointment, so: offset = starts - (now + minutes).
        target_fire_utc = now_utc + timedelta(minutes=minutes)
        offset_seconds = (starts_at_utc - target_fire_utc).total_seconds()
        offset_minutes = int(offset_seconds // 60)
        if offset_minutes < 1:
            await bot.send_message(
                chat_id=message.chat.id,
                text=(
                    f"🚧 dev: ближайшая запись меньше чем через {minutes} мин — "
                    "fire_at оказался бы в прошлом. Возьми меньшее N."
                ),
            )
            return
        # Replace any prior overrides with just our test rule. This isolates
        # the test fire from the global day-before / 60-min pings (otherwise
        # we'd queue extra notifications and create noise).
        repo = AppointmentNotifyOverrideRepository(session)
        await repo.replace_all(
            appointment_id,
            [("offset_before", f"{offset_minutes}m", True)],
        )

    async with session_scope(factory) as session:
        await reschedule_for_appointment(
            session,
            scheduler=data.get("scheduler"),
            appointment_id=appointment_id,
            job_runner=data.get("notify_runner"),
        )

    fire_in_local = (
        target_fire_utc.replace(tzinfo=timezone.utc).astimezone(
            await _tz(factory)
        )
    )
    await bot.send_message(
        chat_id=message.chat.id,
        text=(
            f"🚧 dev: переопределил правила записи #{appointment_id} на "
            f"<code>offset_before {offset_minutes}m</code>.\n"
            f"Ожидаем пинг в {fire_in_local.strftime('%H:%M:%S')} "
            f"(через ≈{minutes} мин)."
        ),
    )


async def _tz(factory: async_sessionmaker[Any]) -> Any:
    async with session_scope(factory) as session:
        return await settings_service.get_timezone(session)
