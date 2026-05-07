"""⚙️ Настройки → 🔔 Настройка уведомлений flow.

Top-level: settings menu (replaces the stub in system.py).
Then: period picker → list of scheduled appointments → per-appointment
rule screen → add-custom-rule mini-flow.

Override semantics: when an appointment has zero override rows, the
screen displays the global notify_rules with toggle/delete buttons.
The first toggle/delete materialises the globals into the override
table for that appointment (so the user's edit doesn't change other
appointments) and applies the change.
"""

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
    NotifyRuleCD,
    PeriodCD,
    SettingsCD,
    TimeCD,
    TimePartCD,
    WizardCD,
)
from src.bot.keyboards.calendar import calendar_kb
from src.bot.keyboards.period_picker import period_picker_kb
from src.bot.keyboards.time_part_picker import (
    time_hour_picker_kb,
    time_minute_picker_kb,
)
from src.bot.keyboards.time_picker import time_picker_kb
from src.bot.states import NotifySettings
from src.bot.ui import advance, finalize, show_in_callback
from src.services import settings_service
from src.services.notifications import reschedule_for_appointment
from src.services.notifications.rules import effective_rules_for_appointment
from src.storage.db import session_scope
from src.storage.repositories.appointment_notify_overrides import (
    AppointmentNotifyOverrideRepository,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository

log = logging.getLogger(__name__)
router = Router(name="notify_settings")


# ---------- entry point: ⚙️ Настройки → 🔔 Настройка уведомлений ----------


@router.callback_query(SettingsCD.filter(F.action == "notifications"))
async def open_notify_settings(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await show_in_callback(
        callback,
        bot=bot,
        text="🔔 Настройка уведомлений\n\nЗа какой период показать записи?",
        reply_markup=period_picker_kb(scope="notify_settings"),
    )
    await state.set_state(NotifySettings.choosing_period)
    await callback.answer()


# ---------- period picker handlers (scope=notify_settings) ------------------


@router.callback_query(PeriodCD.filter(F.scope == "notify_settings"))
async def on_period_picked(
    callback: CallbackQuery,
    callback_data: PeriodCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    if callback_data.kind == "date":
        async with session_scope(factory) as session:
            tz = await settings_service.get_timezone(session)
        today_local = datetime.now(tz=tz).date()
        await show_in_callback(
            callback,
            bot=bot,
            text="Выбери день:",
            reply_markup=calendar_kb(
                anchor=today_local,
                back_callback_data=SettingsCD(action="notifications").pack(),
            ),
        )
        await state.set_state(NotifySettings.choosing_date)
        await callback.answer()
        return
    text, kb = await _build_appointment_list(
        factory, kind=callback_data.kind, anchor=None
    )
    await show_in_callback(callback, bot=bot, text=text, reply_markup=kb)
    await state.set_state(NotifySettings.listing_appointments)
    await callback.answer()


@router.callback_query(NotifySettings.choosing_date, CalendarCD.filter(F.action == "pick"))
async def on_calendar_pick(
    callback: CallbackQuery,
    callback_data: CalendarCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    picked = date.fromisoformat(callback_data.iso_date)
    text, kb = await _build_appointment_list(factory, kind="date", anchor=picked)
    await show_in_callback(callback, bot=bot, text=text, reply_markup=kb)
    await state.set_state(NotifySettings.listing_appointments)
    await callback.answer()


@router.callback_query(NotifySettings.choosing_date, CalendarCD.filter(F.action == "nav"))
async def on_calendar_nav(
    callback: CallbackQuery,
    callback_data: CalendarCD,
    bot: Bot,
    **_: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    anchor = date.fromisoformat(callback_data.iso_date)
    delta = -1 if callback_data.nav == "prev" else 32
    new_anchor = (anchor + timedelta(days=delta)).replace(day=1)
    await show_in_callback(
        callback,
        bot=bot,
        text="Выбери день:",
        reply_markup=calendar_kb(
            anchor=new_anchor,
            back_callback_data=SettingsCD(action="notifications").pack(),
        ),
    )
    await callback.answer()


@router.callback_query(NotifySettings.choosing_date, CalendarCD.filter(F.action == "noop"))
async def on_calendar_noop(callback: CallbackQuery, **_: Any) -> None:
    await callback.answer()


# ---------- list of appointments → per-appointment screen --------------------


async def _build_appointment_list(
    factory: async_sessionmaker[Any], *, kind: str, anchor: date | None
) -> tuple[str, InlineKeyboardMarkup | None]:
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        today_local = datetime.now(tz=tz).date()

        # Resolve [start_local, end_local) per period kind.
        start_local: datetime | None = None
        end_local: datetime | None = None
        if kind == "today":
            start_local = datetime.combine(today_local, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)
        elif kind == "tomorrow":
            tomorrow = today_local + timedelta(days=1)
            start_local = datetime.combine(tomorrow, time(0), tzinfo=tz)
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
        elif kind == "date" and anchor is not None:
            start_local = datetime.combine(anchor, time(0), tzinfo=tz)
            end_local = start_local + timedelta(days=1)

        if start_local is None or end_local is None:
            # "all" — only future from today_local.
            start_local = datetime.combine(today_local, time(0), tzinfo=tz)
            end_local = datetime.combine(date(2100, 1, 1), time(0), tzinfo=tz)

        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        appts = await AppointmentRepository(session).list_in_range(
            start=start_utc, end=end_utc
        )
        repo = ClientRepository(session)
        pairs = []
        for a in appts:
            c = await repo.get(a.client_id)
            if c is not None:
                pairs.append((a, c))

    if not pairs:
        return "🔔 Записей нет — нечего настраивать.", None

    rows: list[list[InlineKeyboardButton]] = []
    pairs.sort(key=lambda p: p[0].starts_at)
    for appt, client in pairs:
        local = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
        date_str = local.strftime("%d.%m")
        time_str = local.strftime("%H:%M")
        label = f"{date_str} {time_str} · {client.name}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=ApptCD(
                        action="notify", appointment_id=appt.id
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад",
                callback_data=SettingsCD(action="notifications").pack(),
            )
        ]
    )
    return (
        "🔔 Выбери запись для настройки уведомлений:",
        InlineKeyboardMarkup(inline_keyboard=rows),
    )


# ---------- per-appointment rule screen --------------------------------------


@router.callback_query(ApptCD.filter(F.action == "notify"))
async def on_open_appt_rules(
    callback: CallbackQuery,
    callback_data: ApptCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _render_appt_rules(
        callback, bot=bot, factory=factory, appointment_id=callback_data.appointment_id
    )
    await state.set_state(NotifySettings.viewing_rules)
    await state.update_data(notify_appointment_id=callback_data.appointment_id)
    await callback.answer()


async def _render_appt_rules(
    callback: CallbackQuery,
    *,
    bot: Bot,
    factory: async_sessionmaker[Any],
    appointment_id: int,
) -> None:
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        appt_repo = AppointmentRepository(session)
        client_repo = ClientRepository(session)
        appt = await appt_repo.get(appointment_id)
        if appt is None:
            await show_in_callback(
                callback, bot=bot, text="Запись не найдена.", reply_markup=None
            )
            return
        client = await client_repo.get(appt.client_id)
        if client is None:
            await show_in_callback(
                callback, bot=bot, text="Клиент удалён.", reply_markup=None
            )
            return
        overrides_repo = AppointmentNotifyOverrideRepository(session)
        overrides = await overrides_repo.list_for_appointment(appointment_id)
        if overrides:
            display = [
                (r.id, r.kind, r.value, r.enabled, True) for r in overrides
            ]  # (id, kind, value, enabled, is_override)
        else:
            globals_ = await NotifyRuleRepository(session).list_all()
            display = [
                (r.id, r.kind, r.value, r.enabled, False) for r in globals_
            ]

    local = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    head = (
        f"🔔 Уведомления для записи:\n"
        f"<b>{html.escape(client.name)}</b> — "
        f"{local.strftime('%d.%m %H:%M')}\n"
    )
    if not display:
        body = "Правил нет — уведомлений по этой записи не будет."
    else:
        body = "Правила:"

    rows: list[list[InlineKeyboardButton]] = []
    for row_id, kind, value, enabled, is_override in display:
        rows.append(_rule_row(row_id, kind, value, enabled, is_override, appointment_id))
    rows.append(
        [
            InlineKeyboardButton(
                text="+ Добавить своё",
                callback_data=NotifyRuleCD(
                    action="add", appointment_id=appointment_id
                ).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад",
                callback_data=SettingsCD(action="notifications").pack(),
            )
        ]
    )
    text = head + "\n" + body
    await show_in_callback(
        callback, bot=bot, text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


def _rule_row(
    row_id: int,
    kind: str,
    value: str,
    enabled: bool,
    is_override: bool,
    appointment_id: int,
) -> list[InlineKeyboardButton]:
    """One row per rule: label + toggle + delete."""
    if kind == "time_day_before":
        label = f"{'✅' if enabled else '☐'} За день в {value}"
    elif kind == "time_same_day":
        label = f"{'✅' if enabled else '☐'} В день в {value}"
    elif kind == "offset_before":
        label = f"{'✅' if enabled else '☐'} За {value} до визита"
    else:
        label = f"{'✅' if enabled else '☐'} {kind} {value}"
    return [
        InlineKeyboardButton(
            text=label,
            callback_data=NotifyRuleCD(
                action="toggle",
                appointment_id=appointment_id,
                rule_id=row_id,
                extra="override" if is_override else "global",
            ).pack(),
        ),
        InlineKeyboardButton(
            text="🗑",
            callback_data=NotifyRuleCD(
                action="delete",
                appointment_id=appointment_id,
                rule_id=row_id,
                extra="override" if is_override else "global",
            ).pack(),
        ),
    ]


@router.callback_query(NotifySettings.viewing_rules, NotifyRuleCD.filter(F.action == "toggle"))
async def on_toggle_rule(
    callback: CallbackQuery,
    callback_data: NotifyRuleCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _materialise_overrides_if_needed(
        factory, appointment_id=callback_data.appointment_id, source=callback_data.extra
    )
    async with session_scope(factory) as session:
        repo = AppointmentNotifyOverrideRepository(session)
        # If we just materialised, rule_id from globals is stale — re-look up.
        # When extra="override" the rule_id is already correct.
        if callback_data.extra == "override":
            row = await session.get(
                __import__(
                    "src.storage.models", fromlist=["AppointmentNotifyOverride"]
                ).AppointmentNotifyOverride,
                callback_data.rule_id,
            )
        else:
            # After materialisation, find the override by (kind, value) snapshot.
            globals_ = await NotifyRuleRepository(session).get(callback_data.rule_id)
            if globals_ is None:
                row = None
            else:
                rows = await repo.list_for_appointment(callback_data.appointment_id)
                row = next(
                    (
                        r for r in rows
                        if r.kind == globals_.kind and r.value == globals_.value
                    ),
                    None,
                )
        if row is not None:
            await repo.set_enabled(row.id, not row.enabled)
    await _reschedule_after_change(
        factory, scheduler=data.get("scheduler"),
        notify_runner=data.get("notify_runner"),
        appointment_id=callback_data.appointment_id,
    )
    await _render_appt_rules(
        callback, bot=bot, factory=factory, appointment_id=callback_data.appointment_id
    )
    await callback.answer()


@router.callback_query(NotifySettings.viewing_rules, NotifyRuleCD.filter(F.action == "delete"))
async def on_delete_rule(
    callback: CallbackQuery,
    callback_data: NotifyRuleCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _materialise_overrides_if_needed(
        factory, appointment_id=callback_data.appointment_id, source=callback_data.extra
    )
    async with session_scope(factory) as session:
        repo = AppointmentNotifyOverrideRepository(session)
        if callback_data.extra == "override":
            await repo.delete_one(callback_data.rule_id)
        else:
            globals_ = await NotifyRuleRepository(session).get(callback_data.rule_id)
            if globals_ is not None:
                rows = await repo.list_for_appointment(callback_data.appointment_id)
                target = next(
                    (
                        r for r in rows
                        if r.kind == globals_.kind and r.value == globals_.value
                    ),
                    None,
                )
                if target is not None:
                    await repo.delete_one(target.id)
    await _reschedule_after_change(
        factory, scheduler=data.get("scheduler"),
        notify_runner=data.get("notify_runner"),
        appointment_id=callback_data.appointment_id,
    )
    await _render_appt_rules(
        callback, bot=bot, factory=factory, appointment_id=callback_data.appointment_id
    )
    await callback.answer()


async def _materialise_overrides_if_needed(
    factory: async_sessionmaker[Any], *, appointment_id: int, source: str
) -> None:
    """If the user is editing 'global' rules for this appointment, snapshot
    the current globals into the override table — then subsequent edits
    only affect this appointment."""
    if source != "global":
        return
    async with session_scope(factory) as session:
        overrides_repo = AppointmentNotifyOverrideRepository(session)
        existing = await overrides_repo.list_for_appointment(appointment_id)
        if existing:
            return
        globals_ = await NotifyRuleRepository(session).list_all()
        await overrides_repo.replace_all(
            appointment_id,
            [(r.kind, r.value, r.enabled) for r in globals_],
        )


async def _reschedule_after_change(
    factory: async_sessionmaker[Any],
    *,
    scheduler: Any,
    notify_runner: Any,
    appointment_id: int,
) -> None:
    async with session_scope(factory) as session:
        await reschedule_for_appointment(
            session,
            scheduler=scheduler,
            appointment_id=appointment_id,
            job_runner=notify_runner,
        )


# ---------- add custom rule mini-flow ---------------------------------------


@router.callback_query(NotifySettings.viewing_rules, NotifyRuleCD.filter(F.action == "add"))
async def on_add_rule_start(
    callback: CallbackQuery,
    callback_data: NotifyRuleCD,
    state: FSMContext,
    bot: Bot,
    **_: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.update_data(notify_appointment_id=callback_data.appointment_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Время дня (накануне)",
                    callback_data=NotifyRuleCD(
                        action="kind",
                        appointment_id=callback_data.appointment_id,
                        extra="time_day_before",
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Время дня (в день)",
                    callback_data=NotifyRuleCD(
                        action="kind",
                        appointment_id=callback_data.appointment_id,
                        extra="time_same_day",
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="За N до визита",
                    callback_data=NotifyRuleCD(
                        action="kind",
                        appointment_id=callback_data.appointment_id,
                        extra="offset_before",
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="← Отмена",
                    callback_data=ApptCD(
                        action="notify", appointment_id=callback_data.appointment_id
                    ).pack(),
                )
            ],
        ]
    )
    await show_in_callback(
        callback,
        bot=bot,
        text="Какое правило добавить?",
        reply_markup=kb,
    )
    await state.set_state(NotifySettings.adding_rule_kind)
    await callback.answer()


@router.callback_query(NotifySettings.adding_rule_kind, NotifyRuleCD.filter(F.action == "kind"))
async def on_add_rule_kind_picked(
    callback: CallbackQuery,
    callback_data: NotifyRuleCD,
    state: FSMContext,
    bot: Bot,
    **_: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.update_data(adding_rule_kind=callback_data.extra)
    if callback_data.extra in {"time_day_before", "time_same_day"}:
        await show_in_callback(
            callback,
            bot=bot,
            text="Выбери время:",
            reply_markup=time_picker_kb(),
        )
        await state.set_state(NotifySettings.adding_rule_time)
    else:
        await show_in_callback(
            callback,
            bot=bot,
            text=(
                "Введи через сколько отправлять "
                "(например <code>60m</code>, <code>2h</code>, <code>1d</code>):"
            ),
            reply_markup=None,
        )
        await state.set_state(NotifySettings.adding_rule_offset)
    await callback.answer()


async def _commit_added_time_rule(
    *,
    bot: Bot,
    state: FSMContext,
    chat_id: int,
    data: dict[str, Any],
    hhmm: str,
) -> None:
    """Apply the picked HH:MM as the new notify rule + bounce back to the
    rules-listing screen. Shared by the picker callback handlers and the
    text-input fallback."""
    state_data = await state.get_data()
    appointment_id = int(state_data["notify_appointment_id"])
    kind = state_data["adding_rule_kind"]
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _add_override_and_apply(
        factory,
        appointment_id=appointment_id,
        kind=kind,
        value=hhmm,
        scheduler=data.get("scheduler"),
        notify_runner=data.get("notify_runner"),
    )
    await advance(
        bot, chat_id=chat_id, state=state,
        text="✅ Правило добавлено.",
        reply_markup=None,
    )
    # Hop back to the rules screen.
    await _render_appt_rules_via_send(
        bot, chat_id, factory=factory, appointment_id=appointment_id
    )
    await state.set_state(NotifySettings.viewing_rules)
    await state.update_data(notify_appointment_id=appointment_id)


@router.callback_query(NotifySettings.adding_rule_time, TimeCD.filter())
async def on_add_rule_time_grid(
    callback: CallbackQuery,
    callback_data: TimeCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    if callback_data.hhmm == "custom":
        await advance(
            bot, chat_id=callback.message.chat.id, state=state,
            text="Выбери час:",
            reply_markup=time_hour_picker_kb(),
        )
        await callback.answer()
        return
    await _commit_added_time_rule(
        bot=bot, state=state, chat_id=callback.message.chat.id,
        data=data, hhmm=callback_data.hhmm,
    )
    await callback.answer()


@router.callback_query(NotifySettings.adding_rule_time, TimePartCD.filter())
async def on_add_rule_time_part(
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
            bot, chat_id=chat_id, state=state,
            text=f"Минуты для {callback_data.hh:02d}:__",
            reply_markup=time_minute_picker_kb(hh=callback_data.hh),
        )
    elif action == "minute":
        hhmm = f"{callback_data.hh:02d}:{callback_data.mm:02d}"
        await _commit_added_time_rule(
            bot=bot, state=state, chat_id=chat_id, data=data, hhmm=hhmm,
        )
    elif action == "back_to_hours":
        await advance(
            bot, chat_id=chat_id, state=state,
            text="Выбери час:",
            reply_markup=time_hour_picker_kb(),
        )
    elif action == "back_to_grid":
        await advance(
            bot, chat_id=chat_id, state=state,
            text="Выбери время:",
            reply_markup=time_picker_kb(),
        )
    await callback.answer()


@router.message(NotifySettings.adding_rule_time, F.text)
async def on_add_rule_time_text(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    """Text-input fallback — kept so power users can still type HH:MM
    instead of tapping. Pickers are the primary path though."""
    if message.text is None:
        return
    raw = message.text.strip()
    try:
        time.fromisoformat(raw if len(raw) == 5 else raw + ":00")
    except ValueError:
        await bot.send_message(
            chat_id=message.chat.id, text="Не понял формат. Попробуй HH:MM:"
        )
        return
    await _commit_added_time_rule(
        bot=bot, state=state, chat_id=message.chat.id,
        data=data, hhmm=raw[:5],
    )


@router.message(NotifySettings.adding_rule_offset, F.text)
async def on_add_rule_offset_text(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    if message.text is None:
        return
    raw = message.text.strip().lower()
    if not raw or raw[-1] not in {"m", "h", "d"} or not raw[:-1].isdigit():
        await bot.send_message(
            chat_id=message.chat.id,
            text=(
                "Не понял. Используй формат "
                "<code>60m</code>, <code>2h</code> или <code>1d</code>:"
            ),
        )
        return
    state_data = await state.get_data()
    appointment_id = int(state_data["notify_appointment_id"])
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    await _add_override_and_apply(
        factory,
        appointment_id=appointment_id,
        kind="offset_before",
        value=raw,
        scheduler=data.get("scheduler"),
        notify_runner=data.get("notify_runner"),
    )
    await bot.send_message(chat_id=message.chat.id, text="✅ Правило добавлено.")
    await _render_appt_rules_via_send(
        bot, message.chat.id, factory=factory, appointment_id=appointment_id
    )
    await state.set_state(NotifySettings.viewing_rules)
    await state.update_data(notify_appointment_id=appointment_id)


async def _add_override_and_apply(
    factory: async_sessionmaker[Any],
    *,
    appointment_id: int,
    kind: str,
    value: str,
    scheduler: Any,
    notify_runner: Any,
) -> None:
    """Materialise globals if needed (so adding a rule doesn't change other
    appointments), append the new rule, then re-plan the schedule."""
    async with session_scope(factory) as session:
        repo = AppointmentNotifyOverrideRepository(session)
        existing = await repo.list_for_appointment(appointment_id)
        if not existing:
            globals_ = await NotifyRuleRepository(session).list_all()
            await repo.replace_all(
                appointment_id,
                [(r.kind, r.value, r.enabled) for r in globals_],
            )
        await repo.add_one(appointment_id, kind=kind, value=value, enabled=True)

    await _reschedule_after_change(
        factory,
        scheduler=scheduler,
        notify_runner=notify_runner,
        appointment_id=appointment_id,
    )


async def _render_appt_rules_via_send(
    bot: Bot,
    chat_id: int,
    *,
    factory: async_sessionmaker[Any],
    appointment_id: int,
) -> None:
    """Reuse the rule-screen rendering for a fresh send_message — used after
    a text-input step where show_in_callback is not available."""
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        appt = await AppointmentRepository(session).get(appointment_id)
        client = (
            await ClientRepository(session).get(appt.client_id) if appt else None
        )
        rules = await effective_rules_for_appointment(session, appointment_id)
        overrides = await AppointmentNotifyOverrideRepository(session).list_for_appointment(
            appointment_id
        )
    if appt is None or client is None:
        await bot.send_message(chat_id=chat_id, text="Запись не найдена.")
        return
    local = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    head = (
        f"🔔 Уведомления для записи:\n"
        f"<b>{html.escape(client.name)}</b> — "
        f"{local.strftime('%d.%m %H:%M')}\n"
    )
    if not rules:
        body = "Правил нет — уведомлений по этой записи не будет."
    else:
        body = "Правила:"

    rows: list[list[InlineKeyboardButton]] = []
    if overrides:
        for o in overrides:
            rows.append(_rule_row(o.id, o.kind, o.value, o.enabled, True, appointment_id))
    else:
        globals_ = await _list_globals_for_chat(factory)
        for g in globals_:
            rows.append(_rule_row(g.id, g.kind, g.value, g.enabled, False, appointment_id))
    rows.append(
        [
            InlineKeyboardButton(
                text="+ Добавить своё",
                callback_data=NotifyRuleCD(
                    action="add", appointment_id=appointment_id
                ).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="← Назад",
                callback_data=SettingsCD(action="notifications").pack(),
            )
        ]
    )
    text = head + "\n" + body
    await bot.send_message(
        chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def _list_globals_for_chat(factory: async_sessionmaker[Any]) -> list[Any]:
    async with session_scope(factory) as session:
        return await NotifyRuleRepository(session).list_all()


# Used to silence unused-import warnings.
_ = (finalize, WizardCD)
