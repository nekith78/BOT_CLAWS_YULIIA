"""Helpers shared between concrete Action implementations.

Kept private (`_common`) — actions are the only callers; tests import
functions directly when needed.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


def parse_local_to_utc(date_iso: str, time_hhmm: str, tz: ZoneInfo) -> datetime:
    """date='YYYY-MM-DD' + time='HH:MM' interpreted as local time in `tz`,
    returned as a naive UTC datetime suitable for storage."""
    target_date = date.fromisoformat(date_iso)
    hh_s, mm_s = time_hhmm.split(":")
    local_dt = datetime.combine(target_date, time(int(hh_s), int(mm_s)), tzinfo=tz)
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def format_local_dt(starts_at_utc: datetime, tz: ZoneInfo) -> str:
    """`DD.MM.YYYY в HH:MM` — used in confirm cards and result messages."""
    local = starts_at_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    return f"{local.strftime('%d.%m.%Y')} в {local.strftime('%H:%M')}"


def format_local_time(starts_at_utc: datetime, tz: ZoneInfo) -> str:
    local = starts_at_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    return local.strftime("%H:%M")


def client_label(name: str, instagram: str | None, idx: int) -> str:
    """Disambiguation label for a client among same-name candidates.

    With instagram → `Имя (@handle)`, otherwise `Имя #N` (1-based).
    """
    if instagram:
        return f"{name} (@{instagram})"
    return f"{name} #{idx + 1}"
