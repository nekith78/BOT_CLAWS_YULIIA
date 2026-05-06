"""AppointmentNotifyOverrideRepository CRUD tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.appointment_notify_overrides import (
    AppointmentNotifyOverrideRepository,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


def _utc(y: int, m: int, d: int, hh: int = 0) -> datetime:
    return datetime(y, m, d, hh, 0, tzinfo=timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_list_for_appointment_empty(session: AsyncSession) -> None:
    repo = AppointmentNotifyOverrideRepository(session)
    assert await repo.list_for_appointment(999) == []


@pytest.mark.asyncio
async def test_add_and_list(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    overrides = AppointmentNotifyOverrideRepository(session)

    client = await clients.create(name="A")
    appt = await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 14))
    await overrides.add_one(appt.id, kind="time_day_before", value="19:00")
    await overrides.add_one(appt.id, kind="offset_before", value="120m", enabled=False)

    rows = await overrides.list_for_appointment(appt.id)
    assert [(r.kind, r.value, r.enabled) for r in rows] == [
        ("time_day_before", "19:00", True),
        ("offset_before", "120m", False),
    ]


@pytest.mark.asyncio
async def test_replace_all_wipes_existing(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    overrides = AppointmentNotifyOverrideRepository(session)

    client = await clients.create(name="A")
    appt = await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 14))
    await overrides.add_one(appt.id, kind="time_day_before", value="20:00")

    await overrides.replace_all(
        appt.id,
        [
            ("offset_before", "60m", True),
            ("offset_before", "24h", True),
        ],
    )

    rows = await overrides.list_for_appointment(appt.id)
    assert {(r.kind, r.value) for r in rows} == {
        ("offset_before", "60m"),
        ("offset_before", "24h"),
    }


@pytest.mark.asyncio
async def test_set_enabled_toggle(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    overrides = AppointmentNotifyOverrideRepository(session)

    client = await clients.create(name="A")
    appt = await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 14))
    row = await overrides.add_one(appt.id, kind="offset_before", value="60m")
    assert row.enabled is True

    updated = await overrides.set_enabled(row.id, False)
    assert updated is not None and updated.enabled is False

    assert await overrides.set_enabled(99999, False) is None


@pytest.mark.asyncio
async def test_delete_one(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    overrides = AppointmentNotifyOverrideRepository(session)

    client = await clients.create(name="A")
    appt = await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 14))
    row = await overrides.add_one(appt.id, kind="time_day_before", value="20:00")

    assert await overrides.delete_one(row.id) is True
    assert await overrides.list_for_appointment(appt.id) == []
    assert await overrides.delete_one(row.id) is False


@pytest.mark.asyncio
async def test_delete_for_appointment_clears_all(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    overrides = AppointmentNotifyOverrideRepository(session)

    client = await clients.create(name="A")
    appt = await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 14))
    await overrides.add_one(appt.id, kind="time_day_before", value="20:00")
    await overrides.add_one(appt.id, kind="offset_before", value="60m")

    await overrides.delete_for_appointment(appt.id)
    assert await overrides.list_for_appointment(appt.id) == []
