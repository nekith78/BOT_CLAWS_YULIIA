"""Resolvers — fuzzy name → entity lookups for the intent layer.

Voice/text commands reference clients by name and appointments by
date/time hints, never by numeric id. Each Action's `plan()` calls
into these helpers to turn the LLM's args into concrete rows.

Convention: when N matches are found, return all of them so the caller
can ask the user to disambiguate (or fail with «не нашёл» on []).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Appointment, Client
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


async def resolve_client(session: AsyncSession, name: str) -> list[Client]:
    """Find clients whose name contains `name` (case-insensitive substring).

    Empty/whitespace input returns [] — caller should prompt for a name.
    """
    cleaned = name.strip()
    if not cleaned:
        return []
    return await ClientRepository(session).search_by_name(cleaned)


async def resolve_appointment(
    session: AsyncSession,
    *,
    client_id: int,
    tz: ZoneInfo,
    date_hint: str | None = None,
    time_hint: str | None = None,
    statuses: tuple[str, ...] = ("scheduled",),
    now_utc: datetime | None = None,
) -> list[Appointment]:
    """Find a client's appointments matching optional date/time hints.

    - With neither hint: future appointments (starts_at ≥ now), nearest first.
    - `date_hint='YYYY-MM-DD'`: narrows to that calendar day in OWNER_TZ.
    - `time_hint='HH:MM'`: further filters to appointments at that local
      time; without `date_hint`, matches that time on any future day.
    """
    repo = AppointmentRepository(session)

    start_utc: datetime | None = None
    end_utc: datetime | None = None
    target_date: date | None = None

    if date_hint is not None:
        target_date = date.fromisoformat(date_hint)
        start_local = datetime.combine(target_date, time(0), tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        # No date hint — restrict to future so we don't pick up past records.
        start_utc = now_utc or datetime.now(tz=timezone.utc).replace(tzinfo=None)

    rows = await repo.list_for_client(
        client_id, statuses=statuses, start=start_utc, end=end_utc
    )

    if time_hint is not None:
        hh, mm = _parse_hhmm(time_hint)
        if target_date is not None:
            target_local = datetime.combine(target_date, time(hh, mm), tzinfo=tz)
            target_utc = target_local.astimezone(timezone.utc).replace(tzinfo=None)
            rows = [r for r in rows if r.starts_at == target_utc]
        else:
            rows = [
                r for r in rows
                if _to_local(r.starts_at, tz).time() == time(hh, mm)
            ]

    return sorted(rows, key=lambda r: r.starts_at)


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh_s, mm_s = value.split(":")
    return int(hh_s), int(mm_s)


def _to_local(starts_at_naive_utc: datetime, tz: ZoneInfo) -> datetime:
    """Convert a naive-UTC `starts_at` (as stored in the DB) to a tz-aware
    local datetime."""
    return starts_at_naive_utc.replace(tzinfo=timezone.utc).astimezone(tz)
