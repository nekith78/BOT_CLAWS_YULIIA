"""Typed CallbackData factories with version field for forward-compat.

Все callback'и используют префиксы и `v=1` — при изменении схемы повышаем v
и фильтр режет старые callback'и с alert'ом «сообщение устарело».
"""
from __future__ import annotations

from typing import Literal

from aiogram.filters.callback_data import CallbackData


class ApptCD(CallbackData, prefix="appt", sep="|"):
    v: int = 1
    action: Literal["view", "move", "cancel", "note", "client", "close"]
    appointment_id: int


class ClientCD(CallbackData, prefix="client", sep="|"):
    v: int = 1
    action: Literal["pick", "view", "edit", "history", "new"]
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
    scope: Literal["lists", "client"] = "lists"
    scope_id: int = 0         # client_id when scope="client"


class WizardCD(CallbackData, prefix="wiz", sep="|"):
    v: int = 1
    action: Literal["save", "edit", "cancel", "skip", "back"]


class DateShortcutCD(CallbackData, prefix="dateshort", sep="|"):
    """Date-step shortcuts on the AddAppointment FSM screen."""

    v: int = 1
    action: Literal["today", "tomorrow", "day_after", "open_calendar", "text_input"]
