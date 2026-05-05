"""Verify model definitions and basic persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Client, Setting


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
