"""List handlers: /today, /tomorrow, /week (and reply-keyboard equivalents)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.callback_data import ApptCD
from src.services import settings_service
from src.services.formatters import (
    format_appointment_line,
    format_date_ru,
    group_by_day,
)
from src.storage.db import session_scope
from src.storage.models import Appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

router = Router(name="lists")


@router.message(Command("today"))
@router.message(F.text == "📅 Сегодня")
async def handle_today(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _send_single_day(bot, factory=factory, chat_id=message.chat.id, day_offset=0)


@router.message(Command("tomorrow"))
@router.message(F.text == "📆 Завтра")
async def handle_tomorrow(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _send_single_day(bot, factory=factory, chat_id=message.chat.id, day_offset=1)


@router.message(Command("week"))
@router.message(F.text == "🗓 Неделя")
async def handle_week(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        today_local = datetime.now(tz=tz).date()
        start_local = datetime.combine(today_local, time(0), tzinfo=tz)
        end_local = start_local + timedelta(days=7)
        appts = await AppointmentRepository(session).list_in_range(
            start=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end=end_local.astimezone(timezone.utc).replace(tzinfo=None),
        )
        pairs = await _hydrate(session, appts)

    if not pairs:
        await bot.send_message(
            chat_id=message.chat.id, text="На неделю записей нет."
        )
        return

    grouped = group_by_day(pairs, tz=tz)
    lines: list[str] = ["🗓 Неделя:\n"]
    inline_rows: list[list[InlineKeyboardButton]] = []
    for day, items in grouped.items():
        lines.append(format_date_ru(datetime.combine(day, time(0))))
        for appt, client in items:
            line = format_appointment_line(appt, client, tz=tz)
            lines.append(line)
            inline_rows.append(
                [
                    InlineKeyboardButton(
                        text=line,
                        callback_data=ApptCD(
                            action="view", appointment_id=appt.id
                        ).pack(),
                    )
                ]
            )
        lines.append("")  # blank line between days
    await bot.send_message(
        chat_id=message.chat.id,
        text="\n".join(lines).rstrip(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_rows),
    )


async def _send_single_day(
    bot: Bot,
    *,
    factory: async_sessionmaker[Any],
    chat_id: int,
    day_offset: int,
) -> None:
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        local_today = datetime.now(tz=tz).date() + timedelta(days=day_offset)
        start_local = datetime.combine(local_today, time(0), tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        appts = await AppointmentRepository(session).list_in_range(
            start=start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end=end_local.astimezone(timezone.utc).replace(tzinfo=None),
        )
        pairs = await _hydrate(session, appts)

    label = {0: "Сегодня", 1: "Завтра"}.get(day_offset, format_date_ru(start_local))
    if not pairs:
        await bot.send_message(chat_id=chat_id, text=f"На {label.lower()} записей нет.")
        return

    rows: list[list[InlineKeyboardButton]] = []
    for appt, client in pairs:
        line = format_appointment_line(appt, client, tz=tz)
        rows.append(
            [
                InlineKeyboardButton(
                    text=line,
                    callback_data=ApptCD(action="view", appointment_id=appt.id).pack(),
                )
            ]
        )
    header = f"{label} — {format_date_ru(start_local)}"
    await bot.send_message(
        chat_id=chat_id,
        text=header,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


async def _hydrate(session: Any, appts: list[Appointment]) -> list[tuple[Appointment, Any]]:
    """Eagerly load Client for each Appointment (we use plain selects, no relationship loading)."""
    if not appts:
        return []
    repo = ClientRepository(session)
    pairs: list[tuple[Appointment, Any]] = []
    for appt in appts:
        client = await repo.get(appt.client_id)
        if client is not None:
            pairs.append((appt, client))
    # Sort already by starts_at via repo; preserve order.
    _ = date  # silence "unused import"
    return pairs
