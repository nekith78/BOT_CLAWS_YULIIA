"""Verify model definitions and basic persistence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import (
    Appointment,
    AppointmentNotifyOverride,
    Client,
    NotifyRule,
    ScheduledJob,
    Setting,
)


@pytest.mark.asyncio
async def test_setting_round_trip(session: AsyncSession) -> None:
    session.add(Setting(key="timezone", value="Asia/Almaty"))
    await session.commit()

    result = await session.execute(select(Setting).where(Setting.key == "timezone"))
    row = result.scalar_one()
    assert row.value == "Asia/Almaty"


@pytest.mark.asyncio
async def test_client_unique_name_collation(session: AsyncSession) -> None:
    session.add(Client(name="Олег Иванов", instagram="oleg_insta"))
    await session.commit()

    result = await session.execute(select(Client).where(Client.name == "Олег Иванов"))
    client = result.scalar_one()
    assert client.id is not None
    assert client.instagram == "oleg_insta"
    assert client.created_at is not None


@pytest.mark.asyncio
async def test_client_optional_fields_default_none(session: AsyncSession) -> None:
    session.add(Client(name="Анна"))
    await session.commit()

    result = await session.execute(select(Client).where(Client.name == "Анна"))
    client = result.scalar_one()
    assert client.instagram is None
    assert client.notes is None


@pytest.mark.asyncio
async def test_appointment_links_client(session: AsyncSession) -> None:
    client = Client(name="Олег")
    session.add(client)
    await session.flush()

    appt = Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
        duration_min=60,
        visit_note="маникюр",
    )
    session.add(appt)
    await session.commit()

    result = await session.execute(select(Appointment))
    saved = result.scalar_one()
    assert saved.status == "scheduled"
    assert saved.duration_min == 60
    assert saved.client_id == client.id


@pytest.mark.asyncio
async def test_appointment_cascade_delete_with_client(session: AsyncSession) -> None:
    client = Client(name="Анна")
    session.add(client)
    await session.flush()
    session.add(Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 7, 10, 0, tzinfo=timezone.utc),
    ))
    await session.commit()

    await session.delete(client)
    await session.commit()

    result = await session.execute(select(Appointment))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_notify_rule_defaults(session: AsyncSession) -> None:
    rule = NotifyRule(kind="time_day_before", value="20:00")
    session.add(rule)
    await session.commit()

    result = await session.execute(select(NotifyRule))
    saved = result.scalar_one()
    assert saved.enabled is True
    assert saved.id is not None


@pytest.mark.asyncio
async def test_scheduled_job_links_appointment(session: AsyncSession) -> None:
    client = Client(name="Олег")
    session.add(client)
    await session.flush()

    appt = Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
    )
    session.add(appt)
    await session.flush()

    job = ScheduledJob(
        appointment_id=appt.id,
        fire_at=datetime(2026, 5, 5, 20, 0, tzinfo=timezone.utc),
        kind="eve_digest",
    )
    session.add(job)
    await session.commit()

    result = await session.execute(select(ScheduledJob))
    saved = result.scalar_one()
    assert saved.sent_at is None
    assert saved.kind == "eve_digest"


@pytest.mark.asyncio
async def test_appointment_notify_override_cascade(session: AsyncSession) -> None:
    """Override rows must disappear together with their appointment."""
    client = Client(name="Олег")
    session.add(client)
    await session.flush()
    appt = Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
    )
    session.add(appt)
    await session.flush()
    override = AppointmentNotifyOverride(
        appointment_id=appt.id, kind="offset_before", value="120m", enabled=True
    )
    session.add(override)
    await session.commit()

    appt_id = appt.id
    await session.delete(appt)
    await session.commit()

    result = await session.execute(
        select(AppointmentNotifyOverride).where(
            AppointmentNotifyOverride.appointment_id == appt_id
        )
    )
    assert result.scalars().all() == []
