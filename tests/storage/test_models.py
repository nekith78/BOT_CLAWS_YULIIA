"""Verify model definitions and basic persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Setting


@pytest.mark.asyncio
async def test_setting_round_trip(session: AsyncSession) -> None:
    session.add(Setting(key="timezone", value="Asia/Almaty"))
    await session.commit()

    result = await session.execute(select(Setting).where(Setting.key == "timezone"))
    row = result.scalar_one()
    assert row.value == "Asia/Almaty"
