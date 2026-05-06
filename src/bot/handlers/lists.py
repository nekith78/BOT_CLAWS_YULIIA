"""List handlers.

Entry points:
- "📋 Записи" reply button → period picker (today/tomorrow/week/month/all/date)
- /today, /tomorrow, /week — slash hotkeys for the same periods

After the user picks a period (or types a date), a list of appointments is
rendered as inline buttons keyed on ApptCD(action=view, ...).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.callback_data import ApptCD, PeriodCD
from src.bot.keyboards.period_picker import period_picker_kb
from src.bot.states import ListsFilter
from src.bot.ui import show_in_callback
from src.services import settings_service
from src.services.formatters import (
    format_appointment_line,
    format_date_ru,
    format_period_header,
    group_by_day,
)
from src.storage.db import session_scope
from src.storage.models import Appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

router = Router(name="lists")


# ---------- entry: «📋 Записи» reply button ---------------------------------


@router.message(F.text == "📋 Записи")
async def handle_lists_menu(message: Message, bot: Bot) -> None:
    await bot.send_message(
        chat_id=message.chat.id,
        text="За какой период показать записи?",
        reply_markup=period_picker_kb(scope="lists"),
    )


# ---------- slash hotkeys ---------------------------------------------------


@router.message(Command("today"))
async def handle_today(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    text, kb = await _build_lists_payload(factory, kind="today", anchor=None)
    await bot.send_message(chat_id=message.chat.id, text=text, reply_markup=kb)


@router.message(Command("tomorrow"))
async def handle_tomorrow(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    text, kb = await _build_lists_payload(factory, kind="tomorrow", anchor=None)
    await bot.send_message(chat_id=message.chat.id, text=text, reply_markup=kb)


@router.message(Command("week"))
async def handle_week(message: Message, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    text, kb = await _build_lists_payload(factory, kind="week", anchor=None)
    await bot.send_message(chat_id=message.chat.id, text=text, reply_markup=kb)


# ---------- period picker callbacks (scope="lists") -------------------------


@router.callback_query(PeriodCD.filter(F.scope == "lists"))
async def on_period_picked(
    callback: CallbackQuery, callback_data: PeriodCD, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    if callback_data.kind == "date":
        await show_in_callback(
            callback,
            bot=bot,
            text="Введи дату YYYY-MM-DD:",
            reply_markup=None,
        )
        await state.set_state(ListsFilter.entering_date)
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    text, kb = await _build_lists_payload(
        factory, kind=callback_data.kind, anchor=None
    )
    await show_in_callback(callback, bot=bot, text=text, reply_markup=kb)
    await callback.answer()


@router.message(ListsFilter.entering_date, F.text)
async def on_date_text(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    if message.text is None:
        return
    try:
        anchor = date.fromisoformat(message.text.strip())
    except ValueError:
        await bot.send_message(
            chat_id=message.chat.id, text="Не понял. Попробуй YYYY-MM-DD:"
        )
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    text, kb = await _build_lists_payload(factory, kind="date", anchor=anchor)
    await bot.send_message(chat_id=message.chat.id, text=text, reply_markup=kb)
    await state.clear()


# ---------- builder ---------------------------------------------------------


async def _build_lists_payload(
    factory: async_sessionmaker[Any],
    *,
    kind: str,
    anchor: date | None,
) -> tuple[str, InlineKeyboardMarkup | None]:
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        today_local = datetime.now(tz=tz).date()

        # Resolve [start_local, end_local) per period kind.
        start_local: datetime | None = None
        end_local: datetime | None = None
        header_anchor = today_local
        if kind == "today":
            start_local = datetime.combine(today_local, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)
        elif kind == "tomorrow":
            tomorrow = today_local + timedelta(days=1)
            start_local = datetime.combine(tomorrow, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)
            header_anchor = tomorrow
        elif kind == "week":
            start_local = datetime.combine(today_local, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=7)
        elif kind == "month":
            month_first = today_local.replace(day=1)
            start_local = datetime.combine(month_first, time(0), tzinfo=tz)
            if month_first.month == 12:
                next_month = month_first.replace(year=month_first.year + 1, month=1)
            else:
                next_month = month_first.replace(month=month_first.month + 1)
            end_local = datetime.combine(next_month, time(0), tzinfo=tz)
            header_anchor = month_first
        elif kind == "date" and anchor is not None:
            start_local = datetime.combine(anchor, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)
            header_anchor = anchor
        # kind == "all" → no window

        start_utc = (
            start_local.astimezone(timezone.utc).replace(tzinfo=None)
            if start_local else None
        )
        end_utc = (
            end_local.astimezone(timezone.utc).replace(tzinfo=None)
            if end_local else None
        )

        repo = AppointmentRepository(session)
        if start_utc is not None and end_utc is not None:
            appts = await repo.list_in_range(start=start_utc, end=end_utc)
        else:
            # "all" — pull a wide window via list_in_range with an
            # epoch..far-future range. find_overlap helpers stay UTC-naive.
            appts = await repo.list_in_range(
                start=datetime(1970, 1, 1),
                end=datetime(2100, 1, 1),
            )
        pairs = await _hydrate(session, appts)

    header = format_period_header(
        kind, anchor=datetime.combine(header_anchor, time(0))
    )
    if not pairs:
        return f"{header}\n\nЗаписей нет.", None

    # Single-day kinds → flat list. Multi-day (week/month/all/date×нет) →
    # group by day with subheaders.
    if kind in {"today", "tomorrow", "date"}:
        rows: list[list[InlineKeyboardButton]] = []
        for appt, client in pairs:
            label = format_appointment_line(appt, client, tz=tz)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=ApptCD(
                            action="view", appointment_id=appt.id
                        ).pack(),
                    )
                ]
            )
        return header, InlineKeyboardMarkup(inline_keyboard=rows)

    grouped = group_by_day(pairs, tz=tz)
    lines: list[str] = [header, ""]
    rows = []
    for day, items in grouped.items():
        lines.append(format_date_ru(datetime.combine(day, time(0))))
        for appt, client in items:
            label = format_appointment_line(appt, client, tz=tz)
            lines.append(label)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=ApptCD(
                            action="view", appointment_id=appt.id
                        ).pack(),
                    )
                ]
            )
        lines.append("")
    return "\n".join(lines).rstrip(), InlineKeyboardMarkup(inline_keyboard=rows)


async def _hydrate(
    session: Any, appts: list[Appointment]
) -> list[tuple[Appointment, Any]]:
    """Eagerly load Client for each Appointment (no relationship loading)."""
    if not appts:
        return []
    repo = ClientRepository(session)
    pairs: list[tuple[Appointment, Any]] = []
    for appt in appts:
        client = await repo.get(appt.client_id)
        if client is not None:
            pairs.append((appt, client))
    return pairs
