"""Display formatters — single source of truth for list/card layout."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from src.storage.models import Appointment, Client

_MONTHS_RU = [
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
_MONTHS_RU_NOM = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]
_WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Convert a datetime to the target tz, treating naive values as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def format_appointment_line(appt: Appointment, client: Client, *, tz: ZoneInfo) -> str:
    local = _to_local(appt.starts_at, tz)
    hhmm = local.strftime("%H:%M")
    if appt.visit_note:
        return f"{hhmm} · {client.name} · {appt.visit_note}"
    return f"{hhmm} · {client.name}"


def format_date_ru(d: datetime) -> str:
    return f"{d.day} {_MONTHS_RU[d.month]} ({_WEEKDAYS_RU[d.weekday()]})"


def group_by_day(
    pairs: list[tuple[Appointment, Client]],
    *,
    tz: ZoneInfo,
) -> OrderedDict[date, list[tuple[Appointment, Client]]]:
    result: OrderedDict[date, list[tuple[Appointment, Client]]] = OrderedDict()
    for appt, client in pairs:
        local = _to_local(appt.starts_at, tz)
        result.setdefault(local.date(), []).append((appt, client))
    return result


def format_period_header(kind: str, *, anchor: datetime) -> str:
    if kind == "today":
        return "Сегодня"
    if kind == "tomorrow":
        return "Завтра"
    if kind == "week":
        return f"Неделя ({format_date_ru(anchor)} → +6 дней)"
    if kind == "month":
        return f"Месяц ({_MONTHS_RU_NOM[anchor.month]} {anchor.year})"
    if kind == "all":
        return "Все записи"
    if kind == "date":
        return format_date_ru(anchor)
    return "Период"
