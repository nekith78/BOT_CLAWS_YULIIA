"""NotifyService.plan_jobs + effective_rules tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.notifications.rules import (
    PlannedJob,
    effective_rules_for_appointment,
    plan_jobs,
)
from src.storage.repositories.appointment_notify_overrides import (
    AppointmentNotifyOverrideRepository,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository

TZ = ZoneInfo("Asia/Almaty")


def _utc_naive_local(local_dt: datetime) -> datetime:
    """Convert a tz-aware local datetime to UTC-naive (storage convention)."""
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_effective_rules_returns_globals_when_no_overrides(
    session: AsyncSession,
) -> None:
    rules_repo = NotifyRuleRepository(session)
    await rules_repo.create(kind="time_day_before", value="20:00", enabled=True)
    await rules_repo.create(kind="offset_before", value="60m", enabled=True)
    clients = ClientRepository(session)
    client = await clients.create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
    )
    result = await effective_rules_for_appointment(session, appt.id)
    assert {(r[0], r[1]) for r in result} == {
        ("time_day_before", "20:00"),
        ("offset_before", "60m"),
    }


@pytest.mark.asyncio
async def test_effective_rules_returns_overrides_when_present(
    session: AsyncSession,
) -> None:
    await NotifyRuleRepository(session).create(
        kind="time_day_before", value="20:00", enabled=True
    )
    clients = ClientRepository(session)
    client = await clients.create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
    )
    await AppointmentNotifyOverrideRepository(session).add_one(
        appt.id, kind="offset_before", value="120m", enabled=True
    )
    result = await effective_rules_for_appointment(session, appt.id)
    # Override fully replaces globals — no time_day_before any more.
    assert [(r[0], r[1]) for r in result] == [("offset_before", "120m")]


@pytest.mark.asyncio
async def test_plan_jobs_default_rules(session: AsyncSession) -> None:
    """20:00 day-before + 60m offset → two future jobs at the right UTC."""
    rules_repo = NotifyRuleRepository(session)
    await rules_repo.create(kind="time_day_before", value="20:00", enabled=True)
    await rules_repo.create(kind="offset_before", value="60m", enabled=True)

    client = await ClientRepository(session).create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
    )

    now_utc = _utc_naive_local(datetime(2026, 5, 4, 12, 0, tzinfo=TZ))
    jobs = await plan_jobs(session, appt, tz=TZ, now_utc=now_utc)
    assert len(jobs) == 2

    # Eve digest: 20:00 on 2026-05-05 in Asia/Almaty → 15:00 UTC.
    eve = next(j for j in jobs if j.kind == "eve_digest")
    expected_eve = _utc_naive_local(datetime(2026, 5, 5, 20, 0, tzinfo=TZ))
    assert eve.fire_at_utc == expected_eve

    # Offset: starts_at − 60 minutes → 13:00 local on the appt day.
    ping = next(j for j in jobs if j.kind == "offset_ping")
    expected_ping = _utc_naive_local(
        datetime(2026, 5, 6, 14, 0, tzinfo=TZ) - timedelta(minutes=60)
    )
    assert ping.fire_at_utc == expected_ping


@pytest.mark.asyncio
async def test_plan_jobs_skips_disabled_rules(session: AsyncSession) -> None:
    rules_repo = NotifyRuleRepository(session)
    await rules_repo.create(kind="offset_before", value="60m", enabled=False)

    client = await ClientRepository(session).create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
    )
    now_utc = _utc_naive_local(datetime(2026, 5, 4, 12, 0, tzinfo=TZ))
    jobs = await plan_jobs(session, appt, tz=TZ, now_utc=now_utc)
    assert jobs == []


@pytest.mark.asyncio
async def test_plan_jobs_skips_past_fire_ats(session: AsyncSession) -> None:
    rules_repo = NotifyRuleRepository(session)
    await rules_repo.create(kind="time_day_before", value="20:00", enabled=True)

    client = await ClientRepository(session).create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
    )
    # Bot booted on 2026-05-06 14:00 — eve_digest of 2026-05-05 20:00 is in the past.
    now_utc = _utc_naive_local(datetime(2026, 5, 6, 13, 30, tzinfo=TZ))
    jobs = await plan_jobs(session, appt, tz=TZ, now_utc=now_utc)
    assert jobs == []


@pytest.mark.asyncio
async def test_plan_jobs_offset_units(session: AsyncSession) -> None:
    rules_repo = NotifyRuleRepository(session)
    await rules_repo.create(kind="offset_before", value="2h", enabled=True)
    await rules_repo.create(kind="offset_before", value="1d", enabled=True)

    client = await ClientRepository(session).create(name="A")
    starts_at_local = datetime(2026, 5, 10, 14, 0, tzinfo=TZ)
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_utc_naive_local(starts_at_local)
    )
    now_utc = _utc_naive_local(datetime(2026, 5, 4, 12, 0, tzinfo=TZ))
    jobs: list[PlannedJob] = await plan_jobs(session, appt, tz=TZ, now_utc=now_utc)

    fire_ats = sorted(j.fire_at_utc for j in jobs)
    assert fire_ats[0] == _utc_naive_local(starts_at_local - timedelta(days=1))
    assert fire_ats[1] == _utc_naive_local(starts_at_local - timedelta(hours=2))
