"""/clients + client card + history with period filter."""

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

from src.bot.callback_data import ApptCD, ClientCD, PeriodCD
from src.bot.keyboards.client_picker import SEARCH_SENTINEL, client_picker_kb
from src.bot.keyboards.period_picker import period_picker_kb
from src.bot.states import BrowseClients, HistoryFilter
from src.bot.ui import advance
from src.services import settings_service
from src.services.formatters import (
    format_appointment_line,
    format_date_ru,
    format_period_header,
    group_by_day,
)
from src.storage.db import session_scope
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

router = Router(name="clients")


# ---------- entry -----------------------------------------------------------


@router.message(Command("clients"))
@router.message(F.text == "👥 Клиенты")
async def handle_clients(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = message.chat.id
    await state.clear()
    async with session_scope(factory) as session:
        recent = await ClientRepository(session).list_recent(limit=20)
    if not recent:
        await bot.send_message(chat_id=chat_id, text="Клиентов пока нет.")
        return
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text="Клиенты:",
        reply_markup=client_picker_kb(recent=recent),
    )


@router.callback_query(ClientCD.filter(F.action == "pick"))
async def on_client_pick(
    callback: CallbackQuery, callback_data: ClientCD, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    if callback_data.client_id == SEARCH_SENTINEL:
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Введи часть имени:",
            reply_markup=None,
        )
        await state.set_state(BrowseClients.searching)
        await callback.answer()
        return
    await _show_client_card(
        bot, chat_id=chat_id, state=state, factory=data["session_factory"],
        client_id=callback_data.client_id,
    )
    await callback.answer()


@router.message(BrowseClients.searching, F.text)
async def on_search_query(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    if message.text is None:
        return
    async with session_scope(factory) as session:
        matches = await ClientRepository(session).search_by_name(message.text, limit=20)
    if not matches:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Никого не нашёл. Попробуй другое имя или /clients.",
            reply_markup=None,
        )
        await state.clear()
        return
    await advance(
        bot,
        chat_id=message.chat.id,
        state=state,
        text="Найденные:",
        reply_markup=client_picker_kb(recent=matches),
    )
    await state.clear()


# ---------- client card -----------------------------------------------------


async def _show_client_card(
    bot: Bot,
    *,
    chat_id: int,
    state: FSMContext,
    factory: async_sessionmaker[Any],
    client_id: int,
) -> None:
    async with session_scope(factory) as session:
        client = await ClientRepository(session).get(client_id)
    if client is None:
        await advance(
            bot, chat_id=chat_id, state=state,
            text="Клиент не найден.", reply_markup=None,
        )
        return
    insta = (
        f"📷 <a href=\"https://instagram.com/{client.instagram}\">{client.instagram}</a>\n"
        if client.instagram
        else ""
    )
    notes = f"📝 {client.notes}\n" if client.notes else ""
    text = f"<b>{client.name}</b>\n{insta}{notes}".rstrip()

    history_btn = InlineKeyboardButton(
        text="История",
        callback_data=ClientCD(action="history", client_id=client_id).pack(),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[history_btn]])
    await advance(bot, chat_id=chat_id, state=state, text=text, reply_markup=kb)


@router.callback_query(ClientCD.filter(F.action == "history"))
async def on_history(
    callback: CallbackQuery, callback_data: ClientCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await advance(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        text="За какой период?",
        reply_markup=period_picker_kb(scope="client", scope_id=callback_data.client_id),
    )
    await callback.answer()


# ---------- period filter ---------------------------------------------------


@router.callback_query(PeriodCD.filter(F.scope == "client"))
async def on_period_picked(
    callback: CallbackQuery, callback_data: PeriodCD, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    if callback_data.kind == "date":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Введи дату YYYY-MM-DD:",
            reply_markup=None,
        )
        await state.update_data(history_client_id=callback_data.scope_id)
        await state.set_state(HistoryFilter.entering_date)
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _render_history(
        bot,
        chat_id=chat_id,
        state=state,
        factory=factory,
        client_id=callback_data.scope_id,
        kind=callback_data.kind,
        anchor=None,
    )
    await callback.answer()


@router.message(HistoryFilter.entering_date, F.text)
async def on_history_date(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if message.text is None:
        return
    try:
        anchor = date.fromisoformat(message.text.strip())
    except ValueError:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Не понял. Попробуй YYYY-MM-DD:",
            reply_markup=None,
        )
        return
    state_data = await state.get_data()
    client_id = state_data.get("history_client_id")
    if client_id is None:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Контекст потерян. Открой /clients заново.",
            reply_markup=None,
        )
        await state.clear()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _render_history(
        bot,
        chat_id=message.chat.id,
        state=state,
        factory=factory,
        client_id=int(client_id),
        kind="date",
        anchor=anchor,
    )
    await state.clear()


async def _render_history(
    bot: Bot,
    *,
    chat_id: int,
    state: FSMContext,
    factory: async_sessionmaker[Any],
    client_id: int,
    kind: str,
    anchor: date | None,
) -> None:
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        today_local = datetime.now(tz=tz).date()
        if anchor is None:
            anchor = today_local

        start_local: datetime | None = None
        end_local: datetime | None = None
        if kind == "today":
            start_local = datetime.combine(today_local, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)
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
        elif kind == "date":
            start_local = datetime.combine(anchor, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)
        # kind == "all" → no window

        start_utc = (
            start_local.astimezone(timezone.utc).replace(tzinfo=None)
            if start_local else None
        )
        end_utc = (
            end_local.astimezone(timezone.utc).replace(tzinfo=None)
            if end_local else None
        )
        appts = await AppointmentRepository(session).list_for_client(
            client_id, start=start_utc, end=end_utc
        )
        client_repo = ClientRepository(session)
        client = await client_repo.get(client_id)

    if client is None:
        await advance(
            bot, chat_id=chat_id, state=state,
            text="Клиент не найден.", reply_markup=None,
        )
        return

    header_anchor = datetime.combine(anchor, time(0), tzinfo=tz)
    header = f"{client.name} — {format_period_header(kind, anchor=header_anchor)}"

    if not appts:
        await advance(
            bot, chat_id=chat_id, state=state, text=f"{header}\n\nЗаписей нет.", reply_markup=None
        )
        return

    pairs = [(appt, client) for appt in appts]
    grouped = group_by_day(pairs, tz=tz)
    lines: list[str] = [header, ""]
    rows: list[list[InlineKeyboardButton]] = []
    for day, items in grouped.items():
        lines.append(format_date_ru(datetime.combine(day, time(0))))
        for appt, c in items:
            label = format_appointment_line(appt, c, tz=tz)
            lines.append(label)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=label,
                        callback_data=ApptCD(action="view", appointment_id=appt.id).pack(),
                    )
                ]
            )
        lines.append("")
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text="\n".join(lines).rstrip(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
