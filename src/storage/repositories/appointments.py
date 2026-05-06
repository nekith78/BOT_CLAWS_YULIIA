"""Appointment repository — CRUD, overlap detection, range queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Appointment


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        client_id: int,
        starts_at: datetime,
        duration_min: int = 60,
        visit_note: str | None = None,
    ) -> Appointment:
        appt = Appointment(
            client_id=client_id,
            starts_at=starts_at,
            duration_min=duration_min,
            visit_note=visit_note,
        )
        self._session.add(appt)
        await self._session.flush()
        return appt

    async def get(self, appointment_id: int) -> Appointment | None:
        return await self._session.get(Appointment, appointment_id)

    async def update_status(self, appointment_id: int, status: str) -> Appointment | None:
        appt = await self.get(appointment_id)
        if appt is None:
            return None
        appt.status = status
        await self._session.flush()
        return appt

    async def reschedule(
        self,
        appointment_id: int,
        *,
        starts_at: datetime,
        duration_min: int | None = None,
    ) -> Appointment | None:
        appt = await self.get(appointment_id)
        if appt is None:
            return None
        appt.starts_at = starts_at
        if duration_min is not None:
            appt.duration_min = duration_min
        await self._session.flush()
        return appt

    async def find_overlap(
        self,
        *,
        starts_at: datetime,
        duration_min: int,
        exclude_id: int | None = None,
    ) -> list[Appointment]:
        """Return scheduled appointments overlapping the proposed slot.

        Two intervals [a,b) and [c,d) overlap iff a < d and c < b.
        SQLite не имеет интервальной арифметики — выбираем кандидатов в окне ±24h
        и фильтруем в Python.
        """
        ends_at = starts_at + timedelta(minutes=duration_min)
        candidates_stmt = (
            select(Appointment)
            .where(
                Appointment.status == "scheduled",
                Appointment.starts_at >= starts_at - timedelta(hours=24),
                Appointment.starts_at <= ends_at + timedelta(hours=24),
            )
        )
        if exclude_id is not None:
            candidates_stmt = candidates_stmt.where(Appointment.id != exclude_id)

        result = await self._session.execute(candidates_stmt)
        candidates = list(result.scalars())

        overlapping: list[Appointment] = []
        for a in candidates:
            a_end = a.starts_at + timedelta(minutes=a.duration_min)
            if a.starts_at < ends_at and starts_at < a_end:
                overlapping.append(a)
        return overlapping

    async def list_in_range(
        self,
        *,
        start: datetime,
        end: datetime,
        statuses: tuple[str, ...] = ("scheduled",),
    ) -> list[Appointment]:
        stmt = (
            select(Appointment)
            .where(
                and_(
                    Appointment.starts_at >= start,
                    Appointment.starts_at < end,
                    Appointment.status.in_(statuses),
                )
            )
            .order_by(Appointment.starts_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def list_for_client(
        self,
        client_id: int,
        *,
        statuses: tuple[str, ...] = ("scheduled", "done"),
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Appointment]:
        """Appointments for a client, newest first. Excludes cancelled by
        default — user policy: cancelled rows must not appear in any list.

        Optional date window narrows by `starts_at` ∈ [start, end).
        """
        stmt = select(Appointment).where(
            Appointment.client_id == client_id,
            Appointment.status.in_(statuses),
        )
        if start is not None:
            stmt = stmt.where(Appointment.starts_at >= start)
        if end is not None:
            stmt = stmt.where(Appointment.starts_at < end)
        stmt = stmt.order_by(desc(Appointment.starts_at))
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def update_visit_note(
        self, appointment_id: int, text: str
    ) -> Appointment | None:
        appt = await self.get(appointment_id)
        if appt is None:
            return None
        appt.visit_note = text
        await self._session.flush()
        return appt

    async def delete(self, appointment_id: int) -> bool:
        appt = await self.get(appointment_id)
        if appt is None:
            return False
        await self._session.delete(appt)
        await self._session.flush()
        return True
