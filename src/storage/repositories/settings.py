"""Settings repository — typed convenience wrappers around key/value storage."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Setting


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        row = await self._session.get(Setting, key)
        return row.value if row is not None else None

    async def get_int(self, key: str, *, default: int | None = None) -> int | None:
        raw = await self.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    async def set(self, key: str, value: str) -> None:
        existing = await self._session.get(Setting, key)
        if existing is None:
            self._session.add(Setting(key=key, value=value))
        else:
            existing.value = value
        await self._session.flush()
