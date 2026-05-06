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
