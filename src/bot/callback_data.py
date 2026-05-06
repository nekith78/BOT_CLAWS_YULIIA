"""Typed CallbackData factories with version field for forward-compat.

Все callback'и используют префиксы и `v=1` — при изменении схемы повышаем v
и фильтр режет старые callback'и с alert'ом «сообщение устарело».
"""
from __future__ import annotations

from typing import Literal

from aiogram.filters.callback_data import CallbackData


class ApptCD(CallbackData, prefix="appt", sep="|"):
    v: int = 1
    action: Literal["view", "move", "cancel", "note", "client", "close", "notify"]
    appointment_id: int


class ClientCD(CallbackData, prefix="client", sep="|"):
    v: int = 1
    action: Literal["pick", "view", "edit", "history", "new", "delete"]
    client_id: int = 0


class CalendarCD(CallbackData, prefix="cal", sep="|"):
    v: int = 1
    action: Literal["pick", "nav", "noop"]
    iso_date: str = ""        # YYYY-MM-DD anchor for the visible month
    nav: str = ""             # "prev" | "next" | ""


class TimeCD(CallbackData, prefix="time", sep="|"):
    v: int = 1
    hhmm: str                 # "HH:MM" or literal "custom"


class TimePartCD(CallbackData, prefix="tpart", sep="|"):
    """Two-step HH:MM picker invoked from "Другое время" — first hour, then
    minute (5-min step). Used in both AddAppointment and EditAppointment.

    - action="hour":           hh is the picked hour (show minute grid for hh)
    - action="minute":         hh+mm is the final pick (commit and advance)
    - action="back_to_hours":  return from minute grid to hour grid
    - action="back_to_grid":   return from hour grid to the main 30-min grid
    """

    v: int = 1
    action: Literal["hour", "minute", "back_to_hours", "back_to_grid"]
    hh: int = 0
    mm: int = 0


class PeriodCD(CallbackData, prefix="period", sep="|"):
    v: int = 1
    kind: Literal["today", "tomorrow", "week", "month", "all", "date"]
    scope: Literal["lists", "client", "notify_settings"] = "lists"
    scope_id: int = 0         # client_id when scope="client"


class WizardCD(CallbackData, prefix="wiz", sep="|"):
    v: int = 1
    action: Literal["save", "edit", "cancel", "skip", "back"]


class DateShortcutCD(CallbackData, prefix="dateshort", sep="|"):
    """Date-step shortcuts on the AddAppointment FSM screen."""

    v: int = 1
    action: Literal["today", "tomorrow", "day_after", "open_calendar"]


class SettingsCD(CallbackData, prefix="settings", sep="|"):
    """⚙️ Настройки top-level menu."""

    v: int = 1
    action: Literal["notifications", "timezone"]


class IntakeCD(CallbackData, prefix="intake", sep="|"):
    """Voice/text intake confirm-card and disambiguation buttons.

    - action="confirm": user pressed ✅ — execute the pending action.
    - action="edit":    user pressed ✏️ Изменить — handoff into the
                        AddAppointment FSM with pre-filled fields.
    - action="cancel":  user pressed ❌ — drop pending state with
                        «❌ Отменено».
    - action="clarify": user picked one disambiguation option — `tag`
                        plus `index` identify the chosen option.

    `tag` is a short id for the pending action stashed in FSM data; it
    binds the keyboard click to the right server-side state.
    """

    v: int = 1
    action: Literal["confirm", "edit", "cancel", "clarify"]
    tag: str = ""
    index: int = 0


class NotifyRuleCD(CallbackData, prefix="nr", sep="|"):
    """Per-appointment notification settings.

    - action="toggle": enable/disable an existing override row by id.
    - action="delete": remove an existing override row by id.
    - action="add":    open the "add custom rule" mini-flow for an appointment.
    - action="kind":   pick a rule kind during the add flow (extra carries the
                       kind: time_day_before | time_same_day | offset_before).
    """

    v: int = 1
    action: Literal["toggle", "delete", "add", "kind"]
    appointment_id: int = 0
    rule_id: int = 0
    extra: str = ""
