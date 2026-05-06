"""ScheduledJobRepository tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.scheduled_jobs import ScheduledJobRepository


def _utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    """UTC-naive datetime — schema convention."""
    return datetime(y, m, d, hh, mm)


async def _seed_appointment(session: AsyncSession, *, hh: int = 14) -> int:
    client = await ClientRepository(session).create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, hh)
    )
    return appt.id


@pytest.mark.asyncio
async def test_replace_for_appointment_wipes_and_inserts(
    session: AsyncSession,
) -> None:
    appt_id = await _seed_appointment(session)
    repo = ScheduledJobRepository(session)
    rows = await repo.replace_for_appointment(
        appt_id,
        [
            (_utc(2026, 5, 5, 20), "eve_digest", None),
            (_utc(2026, 5, 6, 13), "offset_ping", "abc"),
        ],
    )
    assert len(rows) == 2
    assert rows[0].kind == "eve_digest"
    assert rows[1].job_id == "abc"

    # Replace again — first set should be gone.
    await repo.replace_for_appointment(
        appt_id, [(_utc(2026, 5, 5, 19), "eve_digest", None)]
    )
    listed = await repo.list_for_appointment(appt_id)
    assert len(listed) == 1
    assert listed[0].fire_at == _utc(2026, 5, 5, 19)


@pytest.mark.asyncio
async def test_list_due_unsent_window(session: AsyncSession) -> None:
    appt_id = await _seed_appointment(session)
    repo = ScheduledJobRepository(session)
    now = _utc(2026, 5, 6, 14)  # bot just booted at 14:00

    await repo.replace_for_appointment(
        appt_id,
        [
            (_utc(2026, 5, 6, 13), "offset_ping", None),  # 1h ago — due
            (_utc(2026, 5, 6, 6), "offset_ping", None),  # 8h ago — overdue
            (_utc(2026, 5, 6, 15), "offset_ping", None),  # future — not due
        ],
    )

    due = await repo.list_due_unsent(now=now, max_age_hours=6)
    fire_ats = [r.fire_at for r in due]
    assert fire_ats == [_utc(2026, 5, 6, 13)]

    overdue = await repo.list_overdue_to_skip(now=now, max_age_hours=6)
    assert [r.fire_at for r in overdue] == [_utc(2026, 5, 6, 6)]


@pytest.mark.asyncio
async def test_mark_sent_idempotent(session: AsyncSession) -> None:
    appt_id = await _seed_appointment(session)
    repo = ScheduledJobRepository(session)
    rows = await repo.replace_for_appointment(
        appt_id, [(_utc(2026, 5, 6, 13), "offset_ping", None)]
    )
    job = rows[0]

    assert await repo.mark_sent(job.id, when=_utc(2026, 5, 6, 13, 30)) is True
    refreshed = await repo.get(job.id)
    assert refreshed is not None
    assert refreshed.sent_at == _utc(2026, 5, 6, 13, 30)

    # Second call must NOT re-set sent_at.
    assert await repo.mark_sent(job.id, when=_utc(2026, 5, 6, 14, 0)) is False
    final = await repo.get(job.id)
    assert final is not None
    assert final.sent_at == _utc(2026, 5, 6, 13, 30)


@pytest.mark.asyncio
async def test_find_eve_digest_dedup(session: AsyncSession) -> None:
    appt_id = await _seed_appointment(session)
    repo = ScheduledJobRepository(session)
    fire_at = _utc(2026, 5, 5, 20)

    assert await repo.find_eve_digest_at(fire_at) is None

    await repo.replace_for_appointment(appt_id, [(fire_at, "eve_digest", None)])
    found = await repo.find_eve_digest_at(fire_at)
    assert found is not None and found.kind == "eve_digest"
