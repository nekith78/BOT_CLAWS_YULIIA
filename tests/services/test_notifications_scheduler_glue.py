"""reschedule_for_appointment / cancel_for_appointment tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import settings_service
from src.services.notifications import (
    cancel_for_appointment,
    reschedule_for_appointment,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.scheduled_jobs import ScheduledJobRepository

TZ = ZoneInfo("Asia/Almaty")


def _utc_naive_local(local_dt: datetime) -> datetime:
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _runner() -> object:
    """Dummy callable for APScheduler.add_job."""
    return object()


@pytest.mark.asyncio
async def test_reschedule_writes_rows_and_calls_apscheduler(
    session: AsyncSession,
) -> None:
    await NotifyRuleRepository(session).create(
        kind="time_day_before", value="20:00", enabled=True
    )
    await NotifyRuleRepository(session).create(
        kind="offset_before", value="60m", enabled=True
    )
    client = await ClientRepository(session).create(name="A")
    # Far future appointment so both jobs are in-future relative to "now".
    future_local = datetime.now(tz=TZ).replace(microsecond=0) + timedelta(days=10)
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(future_local),
    )

    scheduler = MagicMock()
    runner = _runner()
    await reschedule_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id, job_runner=runner
    )

    rows = await ScheduledJobRepository(session).list_for_appointment(appt.id)
    assert {r.kind for r in rows} == {"eve_digest", "offset_ping"}
    assert all(r.job_id is not None for r in rows)
    # APScheduler called once per row.
    assert scheduler.add_job.call_count == 2


@pytest.mark.asyncio
async def test_reschedule_cancels_old_apscheduler_jobs(
    session: AsyncSession,
) -> None:
    await NotifyRuleRepository(session).create(
        kind="offset_before", value="60m", enabled=True
    )
    client = await ClientRepository(session).create(name="A")
    future_local = datetime.now(tz=TZ).replace(microsecond=0) + timedelta(days=10)
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_utc_naive_local(future_local)
    )
    scheduler = MagicMock()

    await reschedule_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id, job_runner=_runner()
    )
    first_call_count = scheduler.add_job.call_count

    # Reschedule again — same rules, same appointment.
    await reschedule_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id, job_runner=_runner()
    )
    # Must have removed the old job before adding the new one.
    assert scheduler.remove_job.call_count >= 1
    assert scheduler.add_job.call_count > first_call_count


@pytest.mark.asyncio
async def test_reschedule_for_cancelled_appointment_clears_jobs(
    session: AsyncSession,
) -> None:
    await NotifyRuleRepository(session).create(
        kind="offset_before", value="60m", enabled=True
    )
    client = await ClientRepository(session).create(name="A")
    future_local = datetime.now(tz=TZ).replace(microsecond=0) + timedelta(days=10)
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_utc_naive_local(future_local)
    )
    scheduler = MagicMock()
    await reschedule_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id, job_runner=_runner()
    )
    assert (
        len(await ScheduledJobRepository(session).list_for_appointment(appt.id)) > 0
    )

    # Cancel the appointment — reschedule must clear all jobs.
    await AppointmentRepository(session).update_status(appt.id, "cancelled")
    await reschedule_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id, job_runner=_runner()
    )
    assert (
        await ScheduledJobRepository(session).list_for_appointment(appt.id) == []
    )


@pytest.mark.asyncio
async def test_cancel_for_appointment_clears_db_and_apscheduler(
    session: AsyncSession,
) -> None:
    await NotifyRuleRepository(session).create(
        kind="offset_before", value="60m", enabled=True
    )
    client = await ClientRepository(session).create(name="A")
    future_local = datetime.now(tz=TZ).replace(microsecond=0) + timedelta(days=10)
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_utc_naive_local(future_local)
    )
    scheduler = MagicMock()
    await reschedule_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id, job_runner=_runner()
    )

    await cancel_for_appointment(
        session, scheduler=scheduler, appointment_id=appt.id
    )

    assert (
        await ScheduledJobRepository(session).list_for_appointment(appt.id) == []
    )
    assert scheduler.remove_job.call_count >= 1


@pytest.mark.asyncio
async def test_reschedule_without_scheduler_still_writes_rows(
    session: AsyncSession,
) -> None:
    """scheduler=None path — useful for tests / migrations."""
    await NotifyRuleRepository(session).create(
        kind="offset_before", value="60m", enabled=True
    )
    client = await ClientRepository(session).create(name="A")
    future_local = datetime.now(tz=TZ).replace(microsecond=0) + timedelta(days=10)
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_utc_naive_local(future_local)
    )
    await reschedule_for_appointment(
        session, scheduler=None, appointment_id=appt.id, job_runner=None
    )
    rows = await ScheduledJobRepository(session).list_for_appointment(appt.id)
    assert len(rows) == 1
    assert rows[0].job_id is None  # no APScheduler attached


# Used to silence unused-import warning for settings_service.
_ = settings_service
