"""Per-appointment notify override repository.

If `list_for_appointment` returns a non-empty list, those rules **fully
replace** the global notify_rules for that appointment. If it returns
empty, callers fall back to the globals.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import AppointmentNotifyOverride


class AppointmentNotifyOverrideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_appointment(
        self, appointment_id: int
    ) -> list[AppointmentNotifyOverride]:
        stmt = (
            select(AppointmentNotifyOverride)
            .where(AppointmentNotifyOverride.appointment_id == appointment_id)
            .order_by(AppointmentNotifyOverride.id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def add_one(
        self,
        appointment_id: int,
        *,
        kind: str,
        value: str,
        enabled: bool = True,
    ) -> AppointmentNotifyOverride:
        row = AppointmentNotifyOverride(
            appointment_id=appointment_id, kind=kind, value=value, enabled=enabled
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def replace_all(
        self,
        appointment_id: int,
        rules: list[tuple[str, str, bool]],
    ) -> None:
        await self._session.execute(
            delete(AppointmentNotifyOverride).where(
                AppointmentNotifyOverride.appointment_id == appointment_id
            )
        )
        for kind, value, enabled in rules:
            self._session.add(
                AppointmentNotifyOverride(
                    appointment_id=appointment_id,
                    kind=kind,
                    value=value,
                    enabled=enabled,
                )
            )
        await self._session.flush()

    async def set_enabled(
        self, override_id: int, enabled: bool
    ) -> AppointmentNotifyOverride | None:
        row = await self._session.get(AppointmentNotifyOverride, override_id)
        if row is None:
            return None
        row.enabled = enabled
        await self._session.flush()
        return row

    async def delete_one(self, override_id: int) -> bool:
        row = await self._session.get(AppointmentNotifyOverride, override_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def delete_for_appointment(self, appointment_id: int) -> None:
        await self._session.execute(
            delete(AppointmentNotifyOverride).where(
                AppointmentNotifyOverride.appointment_id == appointment_id
            )
        )
        await self._session.flush()
