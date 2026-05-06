"""Tests for settings_service: seed defaults and helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import settings_service
from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.settings import SettingRepository


@pytest.mark.asyncio
async def test_seed_creates_defaults_if_empty(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)

    settings_repo = SettingRepository(session)
    rules_repo = NotifyRuleRepository(session)

    assert await settings_repo.get("timezone") == "Asia/Almaty"
    assert await settings_repo.get("notify_preset") == "eve_offset_60m"
    assert await settings_repo.get_int("default_duration_min") == 60

    rules = await rules_repo.list_enabled()
    assert {(r.kind, r.value) for r in rules} == {
        ("time_day_before", "20:00"),
        ("offset_before", "60m"),
    }


@pytest.mark.asyncio
async def test_seed_is_idempotent(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)
    await settings_service.seed_defaults(session)

    rules = await NotifyRuleRepository(session).list_all()
    assert len(rules) == 2  # не удвоилось


@pytest.mark.asyncio
async def test_get_timezone(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)
    tz = await settings_service.get_timezone(session)
    assert str(tz) == "Asia/Almaty"


@pytest.mark.asyncio
async def test_get_default_duration(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)
    assert await settings_service.get_default_duration_min(session) == 60
