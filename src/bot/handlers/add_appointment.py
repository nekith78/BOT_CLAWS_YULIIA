"""AddAppointment FSM flow — Поток B from spec.

Entry: «+ Запись» reply-text or /new command.
Steps: client → date → time → note → confirm → save.

Conflict-check is layered on top via find_overlap (Task 9c covers it).
"""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.callback_data import (
    CalendarCD,
    ClientCD,
    DateShortcutCD,
    TimeCD,
    WizardCD,
)
from src.bot.keyboards.calendar import calendar_kb
from src.bot.keyboards.client_picker import SEARCH_SENTINEL, client_picker_kb
from src.bot.keyboards.confirm import confirm_kb
from src.bot.keyboards.date_shortcut import date_shortcut_kb
from src.bot.keyboards.time_picker import time_picker_kb
from src.bot.states import AddAppointment
from src.bot.ui import advance, cancel, finalize
from src.services import settings_service
from src.services.formatters import format_date_ru
from src.storage.db import session_scope
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

log = logging.getLogger(__name__)
router = Router(name="add_appointment")

SkipPipe = "—"


# ---------- entry -----------------------------------------------------------


@router.message(F.text == "+ Запись")
@router.message(Command("new"))
async def entry(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = message.chat.id
    await state.clear()
    async with session_scope(factory) as session:
        recent = await ClientRepository(session).list_recent(limit=10)
    text = "Кого записываем?"
    if not recent:
        text = "У тебя ещё нет клиентов. Создаём первого."
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text=text,
        reply_markup=client_picker_kb(recent=recent),
    )
    await state.set_state(AddAppointment.choosing_client)


# ---------- client step -----------------------------------------------------


@router.callback_query(AddAppointment.choosing_client, ClientCD.filter(F.action == "pick"))
async def on_client_picked(
    callback: CallbackQuery, callback_data: ClientCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    if callback_data.client_id == SEARCH_SENTINEL:
        await advance(
            bot, chat_id=chat_id, state=state, text="Введи часть имени клиента:", reply_markup=None
        )
        await state.set_state(AddAppointment.searching_client)
        await callback.answer()
        return
    await state.update_data(client_id=callback_data.client_id)
    await _go_to_date_step(bot, chat_id=chat_id, state=state)
    await callback.answer()


@router.callback_query(AddAppointment.choosing_client, ClientCD.filter(F.action == "new"))
async def on_client_new(callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await advance(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        text="Имя нового клиента:",
        reply_markup=None,
    )
    await state.set_state(AddAppointment.creating_client_name)
    await callback.answer()


@router.message(AddAppointment.searching_client, F.text)
async def on_search_query(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    if message.text is None:
        return
    async with session_scope(factory) as session:
        matches = await ClientRepository(session).search_by_name(message.text, limit=10)
    if not matches:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Не нашёл. Попробуй другое имя или нажми «➕ Новый клиент».",
            reply_markup=client_picker_kb(recent=[]),
        )
    else:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Выбери из найденных:",
            reply_markup=client_picker_kb(recent=matches),
        )
    await state.set_state(AddAppointment.choosing_client)


@router.message(AddAppointment.creating_client_name, F.text)
async def on_new_client_name(message: Message, state: FSMContext, bot: Bot, **_: Any) -> None:
    if message.text is None:
        return
    await state.update_data(new_client_name=message.text.strip())
    await advance(
        bot,
        chat_id=message.chat.id,
        state=state,
        text=f"Instagram (или {SkipPipe} если нет):",
        reply_markup=None,
    )
    await state.set_state(AddAppointment.creating_client_instagram)


@router.message(AddAppointment.creating_client_instagram, F.text)
async def on_new_client_instagram(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    if message.text is None:
        return
    raw = message.text.strip()
    instagram: str | None = None if raw in {SkipPipe, "-", ""} else raw.lstrip("@")
    state_data = await state.get_data()
    name = state_data["new_client_name"]
    async with session_scope(factory) as session:
        client = await ClientRepository(session).create(name=name, instagram=instagram)
        await session.commit()
        client_id = client.id
    await state.update_data(client_id=client_id)
    await _go_to_date_step(bot, chat_id=message.chat.id, state=state)


# ---------- date step -------------------------------------------------------


async def _go_to_date_step(bot: Bot, *, chat_id: int, state: FSMContext) -> None:
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text="Когда?",
        reply_markup=date_shortcut_kb(),
    )
    await state.set_state(AddAppointment.choosing_date)


@router.callback_query(AddAppointment.choosing_date, DateShortcutCD.filter())
async def on_date_shortcut(
    callback: CallbackQuery,
    callback_data: DateShortcutCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
    today = datetime.now(tz=tz).date()
    if callback_data.action == "today":
        await _save_date_and_advance(bot, chat_id=chat_id, state=state, picked=today)
    elif callback_data.action == "tomorrow":
        await _save_date_and_advance(
            bot, chat_id=chat_id, state=state, picked=today + timedelta(days=1)
        )
    elif callback_data.action == "day_after":
        await _save_date_and_advance(
            bot, chat_id=chat_id, state=state, picked=today + timedelta(days=2)
        )
    elif callback_data.action == "open_calendar":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Выбери день:",
            reply_markup=calendar_kb(anchor=today),
        )
    elif callback_data.action == "text_input":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Введи дату в формате YYYY-MM-DD:",
            reply_markup=None,
        )
        await state.set_state(AddAppointment.entering_date)
    await callback.answer()


@router.callback_query(AddAppointment.choosing_date, CalendarCD.filter(F.action == "pick"))
async def on_calendar_pick(
    callback: CallbackQuery, callback_data: CalendarCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    picked = date.fromisoformat(callback_data.iso_date)
    await _save_date_and_advance(
        bot, chat_id=callback.message.chat.id, state=state, picked=picked
    )
    await callback.answer()


@router.callback_query(AddAppointment.choosing_date, CalendarCD.filter(F.action == "nav"))
async def on_calendar_nav(
    callback: CallbackQuery, callback_data: CalendarCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    anchor = date.fromisoformat(callback_data.iso_date)
    delta_days = -1 if callback_data.nav == "prev" else 32
    new_anchor = anchor + timedelta(days=delta_days)
    new_anchor = new_anchor.replace(day=1)
    await advance(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        text="Выбери день:",
        reply_markup=calendar_kb(anchor=new_anchor),
    )
    await callback.answer()


@router.callback_query(AddAppointment.choosing_date, CalendarCD.filter(F.action == "noop"))
async def on_calendar_noop(callback: CallbackQuery, **_: Any) -> None:
    await callback.answer()


@router.message(AddAppointment.entering_date, F.text)
async def on_date_text(message: Message, state: FSMContext, bot: Bot, **_: Any) -> None:
    if message.text is None:
        return
    try:
        picked = date.fromisoformat(message.text.strip())
    except ValueError:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Не понял формат. Попробуй YYYY-MM-DD (например 2026-05-15):",
            reply_markup=None,
        )
        return
    await _save_date_and_advance(bot, chat_id=message.chat.id, state=state, picked=picked)


async def _save_date_and_advance(
    bot: Bot, *, chat_id: int, state: FSMContext, picked: date
) -> None:
    await state.update_data(picked_date=picked.isoformat())
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text=f"📅 {format_date_ru(datetime.combine(picked, time(0)))}\nВо сколько?",
        reply_markup=time_picker_kb(),
    )
    await state.set_state(AddAppointment.choosing_time)


# ---------- time step -------------------------------------------------------


@router.callback_query(AddAppointment.choosing_time, TimeCD.filter())
async def on_time_picked(
    callback: CallbackQuery, callback_data: TimeCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    if callback_data.hhmm == "custom":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Введи время в формате HH:MM:",
            reply_markup=None,
        )
        await state.set_state(AddAppointment.entering_time)
    else:
        await _save_time_and_advance(bot, chat_id=chat_id, state=state, hhmm=callback_data.hhmm)
    await callback.answer()


@router.message(AddAppointment.entering_time, F.text)
async def on_time_text(message: Message, state: FSMContext, bot: Bot, **_: Any) -> None:
    if message.text is None:
        return
    raw = message.text.strip()
    try:
        time.fromisoformat(raw if len(raw) == 5 else raw + ":00")
    except ValueError:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Не понял. Попробуй HH:MM (например 14:30):",
            reply_markup=None,
        )
        return
    await _save_time_and_advance(bot, chat_id=message.chat.id, state=state, hhmm=raw[:5])


async def _save_time_and_advance(
    bot: Bot, *, chat_id: int, state: FSMContext, hhmm: str
) -> None:
    await state.update_data(picked_time=hhmm)
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text="Заметка к визиту? (или нажми Пропустить)",
        reply_markup=_skip_kb(),
    )
    await state.set_state(AddAppointment.entering_note)


def _skip_kb() -> Any:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пропустить", callback_data=WizardCD(action="skip").pack()
                )
            ]
        ]
    )


# ---------- note step -------------------------------------------------------


@router.callback_query(AddAppointment.entering_note, WizardCD.filter(F.action == "skip"))
async def on_note_skipped(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.update_data(visit_note=None)
    await _show_confirm(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        factory=data["session_factory"],
    )
    await callback.answer()


@router.message(AddAppointment.entering_note, F.text)
async def on_note_text(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    if message.text is None:
        return
    await state.update_data(visit_note=message.text.strip())
    await _show_confirm(
        bot,
        chat_id=message.chat.id,
        state=state,
        factory=data["session_factory"],
    )


# ---------- confirm + save --------------------------------------------------


async def _show_confirm(
    bot: Bot, *, chat_id: int, state: FSMContext, factory: async_sessionmaker[Any]
) -> None:
    state_data = await state.get_data()
    async with session_scope(factory) as session:
        client = await ClientRepository(session).get(state_data["client_id"])
    if client is None:
        await finalize(bot, chat_id=chat_id, state=state, text="⚠️ Клиент не найден.")
        return
    picked_date = date.fromisoformat(state_data["picked_date"])
    picked_time_str = state_data["picked_time"]
    visit_note = state_data.get("visit_note")

    def _e(value: str | None) -> str:
        return html.escape(value or "", quote=True)

    insta = f"📷 {_e(client.instagram)}\n" if client.instagram else ""
    note_line = f"📝 {_e(visit_note)}\n" if visit_note else ""
    text = (
        "Записываю:\n"
        f"👤 {_e(client.name)}\n"
        f"📅 {format_date_ru(datetime.combine(picked_date, time(0)))}, {picked_time_str}\n"
        f"{insta}{note_line}".rstrip()
    )
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text=text,
        reply_markup=confirm_kb(),
    )
    await state.set_state(AddAppointment.confirming)


@router.callback_query(AddAppointment.confirming, WizardCD.filter(F.action == "save"))
async def on_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = callback.message.chat.id
    state_data = await state.get_data()
    starts_at_utc, duration, tz = await _resolve_starts_at(factory, state_data)

    async with session_scope(factory) as session:
        repo = AppointmentRepository(session)
        overlap = await repo.find_overlap(starts_at=starts_at_utc, duration_min=duration)
        if overlap:
            client_repo = ClientRepository(session)
            lines: list[str] = []
            for appt in overlap:
                conflict_client = await client_repo.get(appt.client_id)
                if conflict_client is None:
                    continue
                local_starts = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
                local_ends = (
                    appt.starts_at + timedelta(minutes=appt.duration_min)
                ).replace(tzinfo=timezone.utc).astimezone(tz)
                lines.append(
                    f"• {html.escape(conflict_client.name)}, "
                    f"{local_starts.strftime('%H:%M')}–{local_ends.strftime('%H:%M')}"
                )
            await advance(
                bot,
                chat_id=chat_id,
                state=state,
                text="⚠️ В это время уже есть записи:\n" + "\n".join(lines)
                + "\n\nЗаписать всё равно?",
                reply_markup=_conflict_kb(),
            )
            await state.set_state(AddAppointment.resolving_conflict)
            await callback.answer()
            return

        await repo.create(
            client_id=state_data["client_id"],
            starts_at=starts_at_utc,
            duration_min=duration,
            visit_note=state_data.get("visit_note"),
        )
    await finalize(bot, chat_id=chat_id, state=state, text="✅ Запись сохранена.")
    await callback.answer()


async def _resolve_starts_at(
    factory: async_sessionmaker[Any], state_data: dict[str, Any]
) -> tuple[datetime, int, ZoneInfo]:
    """Combine state's picked_date + picked_time in OWNER_TZ, return (UTC naive, duration, tz)."""
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        duration = await settings_service.get_default_duration_min(session)
    picked_date = date.fromisoformat(state_data["picked_date"])
    hh, mm = state_data["picked_time"].split(":")
    local_dt = datetime.combine(picked_date, time(int(hh), int(mm)), tzinfo=tz)
    starts_at_utc = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
    return starts_at_utc, duration, tz


def _conflict_kb() -> Any:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Записать", callback_data=WizardCD(action="save").pack()
                ),
                InlineKeyboardButton(
                    text="Изменить время", callback_data=WizardCD(action="back").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=WizardCD(action="cancel").pack()
                )
            ],
        ]
    )


@router.callback_query(AddAppointment.resolving_conflict, WizardCD.filter(F.action == "save"))
async def on_force_save(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = callback.message.chat.id
    state_data = await state.get_data()
    starts_at_utc, duration, _ = await _resolve_starts_at(factory, state_data)
    async with session_scope(factory) as session:
        await AppointmentRepository(session).create(
            client_id=state_data["client_id"],
            starts_at=starts_at_utc,
            duration_min=duration,
            visit_note=state_data.get("visit_note"),
        )
    await finalize(bot, chat_id=chat_id, state=state, text="✅ Запись сохранена (с пересечением).")
    await callback.answer()


@router.callback_query(AddAppointment.resolving_conflict, WizardCD.filter(F.action == "back"))
async def on_change_time(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await advance(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        text="Выбери другое время:",
        reply_markup=time_picker_kb(),
    )
    await state.set_state(AddAppointment.choosing_time)
    await callback.answer()


@router.callback_query(AddAppointment.resolving_conflict, WizardCD.filter(F.action == "cancel"))
async def on_conflict_cancel(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await cancel(bot, chat_id=callback.message.chat.id, state=state)
    await callback.answer()


@router.callback_query(AddAppointment.confirming, WizardCD.filter(F.action == "edit"))
async def on_edit(callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any) -> None:
    """Restart from client step keeping no draft (план Plan #5 уточнит UX)."""
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = callback.message.chat.id
    async with session_scope(factory) as session:
        recent = await ClientRepository(session).list_recent(limit=10)
    await advance(
        bot,
        chat_id=chat_id,
        state=state,
        text="Кого записываем?",
        reply_markup=client_picker_kb(recent=recent),
    )
    await state.set_state(AddAppointment.choosing_client)
    await callback.answer()


@router.callback_query(AddAppointment.confirming, WizardCD.filter(F.action == "cancel"))
async def on_cancel(callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await cancel(bot, chat_id=callback.message.chat.id, state=state)
    await callback.answer()
