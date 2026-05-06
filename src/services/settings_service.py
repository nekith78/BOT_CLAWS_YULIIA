"""High-level settings access plus default seeding.

`seed_defaults` is idempotent and intended to be called once on startup.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.settings import SettingRepository

DEFAULT_TIMEZONE = "Asia/Almaty"
DEFAULT_PRESET = "eve_offset_60m"
DEFAULT_DURATION_MIN = 60
# Defaults agreed with the user in Plan #3:
# - 20:00 day-before digest of all next-day appointments;
# - exact 60-min ping before each individual appointment.
# Morning 09:00 digest is intentionally absent.
DEFAULT_RULES: list[tuple[str, str, bool]] = [
    ("time_day_before", "20:00", True),
    ("offset_before", "60m", True),
]


async def seed_defaults(session: AsyncSession) -> None:
    """Insert default settings and notify_rules if missing. Idempotent."""
    settings_repo = SettingRepository(session)
    rules_repo = NotifyRuleRepository(session)

    if await settings_repo.get("timezone") is None:
        await settings_repo.set("timezone", DEFAULT_TIMEZONE)
    if await settings_repo.get("notify_preset") is None:
        await settings_repo.set("notify_preset", DEFAULT_PRESET)
    if await settings_repo.get("default_duration_min") is None:
        await settings_repo.set("default_duration_min", str(DEFAULT_DURATION_MIN))

    existing_rules = await rules_repo.list_all()
    if not existing_rules:
        for kind, value, enabled in DEFAULT_RULES:
            await rules_repo.create(kind=kind, value=value, enabled=enabled)


async def get_timezone(session: AsyncSession) -> ZoneInfo:
    raw = await SettingRepository(session).get("timezone") or DEFAULT_TIMEZONE
    return ZoneInfo(raw)


async def get_default_duration_min(session: AsyncSession) -> int:
    repo = SettingRepository(session)
    val = await repo.get_int("default_duration_min", default=DEFAULT_DURATION_MIN)
    assert val is not None
    return val


async def get_preset(session: AsyncSession) -> str:
    return await SettingRepository(session).get("notify_preset") or DEFAULT_PRESET


async def set_preset(session: AsyncSession, preset: str) -> None:
    await SettingRepository(session).set("notify_preset", preset)


async def set_timezone(session: AsyncSession, tz: str) -> None:
    ZoneInfo(tz)  # raises ZoneInfoNotFoundError if invalid
    await SettingRepository(session).set("timezone", tz)


async def set_default_duration_min(session: AsyncSession, minutes: int) -> None:
    if minutes <= 0:
        raise ValueError("duration must be positive")
    await SettingRepository(session).set("default_duration_min", str(minutes))
