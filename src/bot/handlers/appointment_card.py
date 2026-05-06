"""Appointment card: view + move (reschedule) + note edit + cancel."""

from __future__ import annotations

import html
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, cast

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.callback_data import (
    ApptCD,
    CalendarCD,
    DateShortcutCD,
    TimeCD,
    TimePartCD,
    WizardCD,
)
from src.bot.keyboards.appointment_card import appointment_card_kb
from src.bot.keyboards.calendar import calendar_kb
from src.bot.keyboards.date_shortcut import date_shortcut_kb
from src.bot.keyboards.time_part_picker import (
    time_hour_picker_kb,
    time_minute_picker_kb,
)
from src.bot.keyboards.time_picker import time_picker_kb
from src.bot.states import EditAppointment
from src.bot.ui import advance, finalize, show_in_callback
from src.bot.ui import cancel as ui_cancel
from src.services import settings_service
from src.services.formatters import format_date_ru
from src.services.notifications import (
    cancel_for_appointment,
    reschedule_for_appointment,
)
from src.storage.db import session_scope
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

log = logging.getLogger(__name__)
router = Router(name="appointment_card")


def _e(value: str | None) -> str:
    """Escape user-supplied text for HTML parse_mode (issue #1)."""
    return html.escape(value or "", quote=True)


# ---------- view ------------------------------------------------------------


@router.callback_query(ApptCD.filter(F.action == "view"))
async def on_view(
    callback: CallbackQuery, callback_data: ApptCD, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        appt = await AppointmentRepository(session).get(callback_data.appointment_id)
        client = (
            await ClientRepository(session).get(appt.client_id) if appt is not None else None
        )
    if appt is None or client is None:
        await show_in_callback(
            callback, bot=bot, text="Запись не найдена.", reply_markup=None
        )
        await callback.answer()
        return

    local = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    note = f"📝 {_e(appt.visit_note)}\n" if appt.visit_note else ""
    insta = (
        f"📷 <a href=\"https://instagram.com/{_e(client.instagram)}\">{_e(client.instagram)}</a>\n"
        if client.instagram
        else ""
    )
    status_labels = {
        "scheduled": "🕓 Запланирована",
        "done": "✅ Выполнена",
        "cancelled": "❌ Отменена",
    }
    status_label = status_labels.get(appt.status, _e(appt.status))
    text = (
        f"<b>{_e(client.name)}</b>\n"
        f"📅 {format_date_ru(local)}, {local.strftime('%H:%M')}\n"
        f"{insta}{note}{status_label}"
    )
    kb = (
        appointment_card_kb(appointment_id=appt.id)
        if appt.status == "scheduled"
        else _closed_kb(appt.id)
    )
    # show_in_callback edits the clicked message; the wizard's flow_message_id
    # is left alone (issue #3).
    await show_in_callback(callback, bot=bot, text=text, reply_markup=kb)
    await callback.answer()


def _closed_kb(appointment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Закрыть",
                    callback_data=ApptCD(action="close", appointment_id=appointment_id).pack(),
                )
            ]
        ]
    )


# ---------- close -----------------------------------------------------------


@router.callback_query(ApptCD.filter(F.action == "close"))
async def on_close(callback: CallbackQuery, **_: Any) -> None:
    if callback.message is None:
        await callback.answer()
        return
    msg = callback.message
    if hasattr(msg, "edit_reply_markup"):
        try:
            await msg.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("close edit_reply_markup failed: %s", exc)
    await callback.answer()


# ---------- helpers --------------------------------------------------------


async def _load_active(
    factory: async_sessionmaker[Any], appointment_id: int
) -> Any | None:
    """Fetch appointment only if still scheduled. Returns None for missing
    or non-scheduled rows so callers can refuse the action (issue #4)."""
    async with session_scope(factory) as session:
        appt = await AppointmentRepository(session).get(appointment_id)
    if appt is None or appt.status != "scheduled":
        return None
    return appt


# ---------- note edit -------------------------------------------------------


@router.callback_query(ApptCD.filter(F.action == "note"))
async def on_note_start(
    callback: CallbackQuery, callback_data: ApptCD, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    if await _load_active(factory, callback_data.appointment_id) is None:
        await callback.answer("Эта запись уже не активна.", show_alert=True)
        return
    # Re-anchor the wizard's flow_message to THIS card (the one the user
    # clicked), not whatever stale id might be left in state.
    if isinstance(callback.message, Message):
        await state.update_data(flow_message_id=callback.message.message_id)
    await state.update_data(edit_appointment_id=callback_data.appointment_id)
    await show_in_callback(
        callback, bot=bot, text="Новая заметка:", reply_markup=None
    )
    await state.set_state(EditAppointment.entering_note)
    await callback.answer()


@router.message(EditAppointment.entering_note, F.text)
async def on_note_text(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    if message.text is None:
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    state_data = await state.get_data()
    appt_id = state_data.get("edit_appointment_id")
    if appt_id is None:
        await finalize(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Контекст потерян.",
        )
        return
    async with session_scope(factory) as session:
        repo = AppointmentRepository(session)
        appt = await repo.get(int(appt_id))
        if appt is None or appt.status != "scheduled":
            updated = None
        else:
            updated = await repo.update_visit_note(int(appt_id), message.text.strip())
    if updated is None:
        await finalize(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="⚠️ Запись не найдена или уже не активна. Изменения не сохранены.",
        )
        return
    await finalize(
        bot, chat_id=message.chat.id, state=state, text="✅ Заметка обновлена."
    )


# ---------- cancel ----------------------------------------------------------


@router.callback_query(ApptCD.filter(F.action == "cancel"))
async def on_cancel_start(
    callback: CallbackQuery, callback_data: ApptCD, state: FSMContext, bot: Bot, **data: Any
) -> None:
    log.info("on_cancel_start: appt_id=%s", callback_data.appointment_id)
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    active = await _load_active(factory, callback_data.appointment_id)
    log.info("on_cancel_start: _load_active → %s", "active" if active else "None")
    if active is None:
        await callback.answer("Эта запись уже не активна.", show_alert=True)
        return
    # Re-anchor the wizard's flow_message to THIS card.
    if isinstance(callback.message, Message):
        await state.update_data(flow_message_id=callback.message.message_id)
    await state.update_data(cancel_appointment_id=callback_data.appointment_id)
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, отменить",
                    callback_data=WizardCD(action="save").pack(),
                ),
                InlineKeyboardButton(
                    text="Не надо",
                    callback_data=WizardCD(action="cancel").pack(),
                ),
            ]
        ]
    )
    await show_in_callback(
        callback,
        bot=bot,
        text="Точно отменяем эту запись?",
        reply_markup=confirm_kb,
    )
    await state.set_state(EditAppointment.choosing_new_date)
    # Repurpose state — using a flag to tell apart from reschedule.
    await state.update_data(cancel_confirm=True)
    await callback.answer()


@router.callback_query(EditAppointment.choosing_new_date, WizardCD.filter(F.action == "save"))
async def on_cancel_confirmed(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any
) -> None:
    log.info("on_cancel_confirmed entry")
    if callback.message is None:
        await callback.answer()
        return
    state_data = await state.get_data()
    log.info("on_cancel_confirmed: state_data=%s", state_data)
    if not state_data.get("cancel_confirm"):
        log.info("on_cancel_confirmed: cancel_confirm not set, ignoring")
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    appt_id = int(state_data["cancel_appointment_id"])
    log.info("on_cancel_confirmed: cancelling appt_id=%s", appt_id)
    async with session_scope(factory) as session:
        repo = AppointmentRepository(session)
        appt = await repo.get(appt_id)
        if appt is None:
            updated = None
        elif appt.status != "scheduled":
            # Already done/cancelled — refuse silently.
            updated = None
        else:
            updated = await repo.update_status(appt_id, "cancelled")
    if updated is None:
        await finalize(
            bot,
            chat_id=callback.message.chat.id,
            state=state,
            text="⚠️ Запись не найдена или уже не активна.",
        )
        await callback.answer()
        return
    # Drop notifications for this appointment.
    async with session_scope(factory) as session:
        await cancel_for_appointment(
            session, scheduler=data.get("scheduler"), appointment_id=appt_id
        )
    await finalize(
        bot, chat_id=callback.message.chat.id, state=state, text="❌ Запись отменена."
    )
    await callback.answer()


@router.callback_query(EditAppointment.choosing_new_date, WizardCD.filter(F.action == "cancel"))
async def on_cancel_aborted(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    state_data = await state.get_data()
    if state_data.get("cancel_confirm"):
        await ui_cancel(bot, chat_id=callback.message.chat.id, state=state)
    await callback.answer()


# ---------- move (reschedule) ----------------------------------------------


@router.callback_query(ApptCD.filter(F.action == "move"))
async def on_move_start(
    callback: CallbackQuery, callback_data: ApptCD, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    if await _load_active(factory, callback_data.appointment_id) is None:
        await callback.answer("Эта запись уже не активна.", show_alert=True)
        return
    # Re-anchor the wizard's flow_message to THIS card.
    if isinstance(callback.message, Message):
        await state.update_data(flow_message_id=callback.message.message_id)
    await state.update_data(
        edit_appointment_id=callback_data.appointment_id,
        cancel_confirm=False,
    )
    await show_in_callback(
        callback,
        bot=bot,
        text="Новая дата:",
        reply_markup=date_shortcut_kb(),
    )
    await state.set_state(EditAppointment.choosing_new_date)
    await callback.answer()


@router.callback_query(EditAppointment.choosing_new_date, CalendarCD.filter(F.action == "pick"))
async def on_move_calendar_pick(
    callback: CallbackQuery, callback_data: CalendarCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await _save_new_date(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        picked=date.fromisoformat(callback_data.iso_date),
    )
    await callback.answer()


@router.callback_query(EditAppointment.choosing_new_date, CalendarCD.filter(F.action == "nav"))
async def on_move_calendar_nav(
    callback: CallbackQuery, callback_data: CalendarCD, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    anchor = date.fromisoformat(callback_data.iso_date)
    delta = -1 if callback_data.nav == "prev" else 32
    new_anchor = (anchor + timedelta(days=delta)).replace(day=1)
    await advance(
        bot,
        chat_id=callback.message.chat.id,
        state=state,
        text="Выбери день:",
        reply_markup=calendar_kb(anchor=new_anchor),
    )
    await callback.answer()


@router.callback_query(EditAppointment.choosing_new_date, CalendarCD.filter(F.action == "noop"))
async def on_move_calendar_noop(callback: CallbackQuery, **_: Any) -> None:
    await callback.answer()


@router.callback_query(EditAppointment.choosing_new_date, DateShortcutCD.filter())
async def on_move_date_shortcut(
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
        await _save_new_date(bot, chat_id=chat_id, state=state, picked=today)
    elif callback_data.action == "tomorrow":
        await _save_new_date(bot, chat_id=chat_id, state=state, picked=today + timedelta(days=1))
    elif callback_data.action == "day_after":
        await _save_new_date(bot, chat_id=chat_id, state=state, picked=today + timedelta(days=2))
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
            text="Дата YYYY-MM-DD:",
            reply_markup=None,
        )
        # Reuse choosing_new_date for text input — simpler than a new state.
        await state.update_data(awaiting_date_text=True)
    await callback.answer()


@router.message(EditAppointment.choosing_new_date, F.text)
async def on_move_date_text(message: Message, state: FSMContext, bot: Bot, **_: Any) -> None:
    state_data = await state.get_data()
    if not state_data.get("awaiting_date_text") or message.text is None:
        return
    try:
        picked = date.fromisoformat(message.text.strip())
    except ValueError:
        await advance(
            bot,
            chat_id=message.chat.id,
            state=state,
            text="Не понял. YYYY-MM-DD:",
            reply_markup=None,
        )
        return
    await state.update_data(awaiting_date_text=False)
    await _save_new_date(bot, chat_id=message.chat.id, state=state, picked=picked)


async def _save_new_date(
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
    await state.set_state(EditAppointment.choosing_new_time)


@router.callback_query(EditAppointment.choosing_new_time, TimeCD.filter())
async def on_move_time_picked(
    callback: CallbackQuery, callback_data: TimeCD, state: FSMContext, bot: Bot, **data: Any
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
            text="Выбери час:",
            reply_markup=time_hour_picker_kb(),
        )
        await callback.answer()
        return
    hh, mm = callback_data.hhmm.split(":")
    await _save_move(
        bot,
        callback=callback,
        state=state,
        data=data,
        hh=int(hh),
        mm=int(mm),
    )


@router.callback_query(EditAppointment.choosing_new_time, TimePartCD.filter())
async def on_move_time_part(
    callback: CallbackQuery,
    callback_data: TimePartCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    chat_id = callback.message.chat.id
    action = callback_data.action

    if action == "hour":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text=f"Минуты для {callback_data.hh:02d}:__",
            reply_markup=time_minute_picker_kb(hh=callback_data.hh),
        )
        await callback.answer()
        return
    if action == "minute":
        await _save_move(
            bot,
            callback=callback,
            state=state,
            data=data,
            hh=callback_data.hh,
            mm=callback_data.mm,
        )
        return
    if action == "back_to_hours":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Выбери час:",
            reply_markup=time_hour_picker_kb(),
        )
    elif action == "back_to_grid":
        await advance(
            bot,
            chat_id=chat_id,
            state=state,
            text="Во сколько?",
            reply_markup=time_picker_kb(),
        )
    await callback.answer()


async def _save_move(
    bot: Bot,
    *,
    callback: CallbackQuery,
    state: FSMContext,
    data: dict[str, Any],
    hh: int,
    mm: int,
) -> None:
    """Commit the picked HH:MM as the appointment's new time, with overlap
    check and notification rescheduling. Used by both the 30-min grid and
    the two-step custom picker."""
    if callback.message is None:
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = callback.message.chat.id
    state_data = await state.get_data()
    appt_id = int(state_data["edit_appointment_id"])
    picked_date = date.fromisoformat(state_data["picked_date"])

    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        duration = await settings_service.get_default_duration_min(session)
        local_dt = datetime.combine(picked_date, time(hh, mm), tzinfo=tz)
        starts_at_utc = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
        repo = AppointmentRepository(session)
        # Re-check status before write — appointment may have been cancelled
        # between move-start and now (issue #4).
        existing = await repo.get(appt_id)
        if existing is None or existing.status != "scheduled":
            await finalize(
                bot,
                chat_id=chat_id,
                state=state,
                text="⚠️ Запись не найдена или уже не активна.",
            )
            await callback.answer()
            return
        overlap = await repo.find_overlap(
            starts_at=starts_at_utc, duration_min=duration, exclude_id=appt_id
        )
        if overlap:
            await finalize(
                bot,
                chat_id=chat_id,
                state=state,
                text="⚠️ В это время уже есть другая запись. Перенос отменён.",
            )
            await callback.answer()
            return
        rescheduled = await repo.reschedule(
            appt_id, starts_at=starts_at_utc, duration_min=duration
        )
    if rescheduled is None:
        await finalize(
            bot, chat_id=chat_id, state=state, text="⚠️ Запись не найдена."
        )
        await callback.answer()
        return
    async with session_scope(factory) as session:
        await reschedule_for_appointment(
            session,
            scheduler=data.get("scheduler"),
            appointment_id=appt_id,
            job_runner=data.get("notify_runner"),
        )
    await finalize(bot, chat_id=chat_id, state=state, text="✅ Перенесено.")
    await callback.answer()
