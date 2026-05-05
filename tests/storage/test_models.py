"""Verify model definitions and basic persistence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Appointment, Client, Setting


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
