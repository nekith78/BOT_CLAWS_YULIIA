"""Tests for resolve_client / resolve_appointment."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.resolvers import resolve_appointment, resolve_client
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    local = datetime.combine(d, time(hh, mm), tzinfo=TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


# --- resolve_client -------------------------------------------------------


async def test_resolve_client_returns_empty_for_blank_name(
    session: AsyncSession,
) -> None:
    assert await resolve_client(session, "") == []
    assert await resolve_client(session, "   ") == []


async def test_resolve_client_returns_empty_when_no_match(
    session: AsyncSession,
) -> None:
    await ClientRepository(session).create(name="Иван")
    matches = await resolve_client(session, "Олег")
    assert matches == []


async def test_resolve_client_finds_exact_match_case_insensitive(
    session: AsyncSession,
) -> None:
    await ClientRepository(session).create(name="Ира")
    matches = await resolve_client(session, "ира")
    assert len(matches) == 1
    assert matches[0].name == "Ира"


async def test_resolve_client_returns_all_substring_matches(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Ирина")
    await repo.create(name="Олег")
    matches = await resolve_client(session, "Ир")
    assert {c.name for c in matches} == {"Ира", "Ирина"}


# --- resolve_appointment --------------------------------------------------


async def test_resolve_appointment_no_hints_returns_future_only(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)

    today = date(2026, 5, 7)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)
    next_week = today + timedelta(days=7)

    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(yesterday, 14, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(tomorrow, 11, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(next_week, 16, 0),
        duration_min=60,
    )

    now_utc = _local_to_utc(today, 12, 0)
    matches = await resolve_appointment(
        session, client_id=client.id, tz=TZ, now_utc=now_utc
    )

    # Yesterday's appointment is excluded; remaining are nearest-first.
    assert len(matches) == 2
    assert matches[0].starts_at < matches[1].starts_at


async def test_resolve_appointment_date_hint_narrows_to_one_day(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)

    target = date(2026, 5, 8)
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(target, 11, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(target, 14, 30),
        duration_min=60,
    )
    # Different day — must be excluded.
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 9), 11, 0),
        duration_min=60,
    )

    matches = await resolve_appointment(
        session, client_id=client.id, tz=TZ, date_hint=target.isoformat()
    )

    assert len(matches) == 2
    assert matches[0].starts_at < matches[1].starts_at


async def test_resolve_appointment_date_and_time_hints_exact_match(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)

    target = date(2026, 5, 8)
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(target, 11, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(target, 14, 30),
        duration_min=60,
    )

    matches = await resolve_appointment(
        session,
        client_id=client.id,
        tz=TZ,
        date_hint=target.isoformat(),
        time_hint="14:30",
    )

    assert len(matches) == 1
    expected = _local_to_utc(target, 14, 30)
    assert matches[0].starts_at == expected


async def test_resolve_appointment_time_hint_only_matches_across_days(
    session: AsyncSession,
) -> None:
    """«Перенеси на 14:00» without specifying date — match all 14:00 slots."""
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)

    today = date(2026, 5, 7)
    later = date(2026, 5, 12)
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today + timedelta(days=1), 14, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(later, 14, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today + timedelta(days=1), 16, 0),
        duration_min=60,
    )

    now_utc = _local_to_utc(today, 12, 0)
    matches = await resolve_appointment(
        session,
        client_id=client.id,
        tz=TZ,
        time_hint="14:00",
        now_utc=now_utc,
    )

    assert len(matches) == 2
    for m in matches:
        local = m.starts_at.replace(tzinfo=timezone.utc).astimezone(TZ)
        assert local.time() == time(14, 0)


async def test_resolve_appointment_excludes_cancelled_by_default(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)

    appt = await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 10), 14, 0),
        duration_min=60,
    )
    await appt_repo.update_status(appt.id, "cancelled")

    matches = await resolve_appointment(
        session, client_id=client.id, tz=TZ, now_utc=_local_to_utc(date(2026, 5, 7), 12, 0)
    )
    assert matches == []


async def test_resolve_appointment_returns_empty_when_no_match(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    matches = await resolve_appointment(
        session, client_id=client.id, tz=TZ, now_utc=datetime(2026, 5, 7, 12, 0)
    )
    assert matches == []
