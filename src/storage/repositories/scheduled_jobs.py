"""ScheduledJob repository — book-keeping for in-flight notifications.

ScheduledJob rows are the durable record of *what should fire when*. The
APScheduler jobstore is a separate concern; the two are kept in sync by
NotifyService. Recovery on startup walks ScheduledJob rows whose
sent_at is NULL and decides whether to (a) send late, (b) skip and
mark, depending on age.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import ScheduledJob


class ScheduledJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_appointment(
        self,
        appointment_id: int,
        jobs: list[tuple[datetime, str, str | None]],
    ) -> list[ScheduledJob]:
        """Wipe rows for the appointment and insert the given (fire_at, kind,
        job_id) tuples. Returns the inserted rows in insertion order."""
        await self._session.execute(
            delete(ScheduledJob).where(ScheduledJob.appointment_id == appointment_id)
        )
        rows: list[ScheduledJob] = []
        for fire_at, kind, job_id in jobs:
            row = ScheduledJob(
                appointment_id=appointment_id,
                fire_at=fire_at,
                kind=kind,
                job_id=job_id,
            )
            self._session.add(row)
            rows.append(row)
        await self._session.flush()
        return rows

    async def get(self, scheduled_job_id: int) -> ScheduledJob | None:
        return await self._session.get(ScheduledJob, scheduled_job_id)

    async def list_due_unsent(
        self,
        *,
        now: datetime,
        max_age_hours: int = 6,
    ) -> list[ScheduledJob]:
        """fire_at ∈ [now − max_age_hours, now] AND sent_at IS NULL.

        These are notifications the bot was supposed to fire while it was
        offline. They get re-sent with a "(с задержкой)" prefix.
        """
        cutoff = now - timedelta(hours=max_age_hours)
        stmt = (
            select(ScheduledJob)
            .where(
                and_(
                    ScheduledJob.sent_at.is_(None),
                    ScheduledJob.fire_at >= cutoff,
                    ScheduledJob.fire_at <= now,
                )
            )
            .order_by(ScheduledJob.fire_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def list_overdue_to_skip(
        self,
        *,
        now: datetime,
        max_age_hours: int = 6,
    ) -> list[ScheduledJob]:
        """sent_at IS NULL AND fire_at < now − max_age_hours.

        Too old to send — to be marked as sent_at=now and forgotten so
        the dispatcher does not loop on them on every restart.
        """
        cutoff = now - timedelta(hours=max_age_hours)
        stmt = (
            select(ScheduledJob)
            .where(
                and_(
                    ScheduledJob.sent_at.is_(None),
                    ScheduledJob.fire_at < cutoff,
                )
            )
            .order_by(ScheduledJob.fire_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def mark_sent(self, scheduled_job_id: int, *, when: datetime) -> bool:
        row = await self.get(scheduled_job_id)
        if row is None or row.sent_at is not None:
            return False
        row.sent_at = when
        await self._session.flush()
        return True

    async def find_eve_digest_at(self, fire_at: datetime) -> ScheduledJob | None:
        """Dedup helper: at most one eve_digest may be scheduled at the same
        fire_at moment. Returns the existing one if any so the caller can
        skip creating a duplicate."""
        stmt = select(ScheduledJob).where(
            and_(
                ScheduledJob.kind == "eve_digest",
                ScheduledJob.fire_at == fire_at,
                ScheduledJob.sent_at.is_(None),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_appointment(self, appointment_id: int) -> list[ScheduledJob]:
        stmt = (
            select(ScheduledJob)
            .where(ScheduledJob.appointment_id == appointment_id)
            .order_by(ScheduledJob.fire_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())
