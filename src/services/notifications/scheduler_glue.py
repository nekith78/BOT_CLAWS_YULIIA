"""Bridge between the planner (`rules.plan_jobs`), the durable record
(`ScheduledJobRepository`) and APScheduler.

These functions are the only thing booking handlers need to call —
everything below stays an implementation detail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services import settings_service
from src.services.notifications.rules import plan_jobs
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.scheduled_jobs import ScheduledJobRepository

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

log = logging.getLogger(__name__)


def _now_utc_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _ensure_utc_aware(dt_naive: datetime) -> datetime:
    return dt_naive.replace(tzinfo=timezone.utc)


async def reschedule_for_appointment(
    session: AsyncSession,
    *,
    scheduler: AsyncIOScheduler | None,
    appointment_id: int,
    job_runner: Any | None = None,
) -> None:
    """Recompute the appointment's notification schedule and persist it.

    `scheduler` may be None in tests / dry-run modes. When None, only the
    DB rows are written; APScheduler is not touched.

    `job_runner` is the callable APScheduler should invoke at fire_at.
    Wired in main.py via a lambda that knows about the bot. Optional in
    tests.
    """
    appt_repo = AppointmentRepository(session)
    sj_repo = ScheduledJobRepository(session)

    appt = await appt_repo.get(appointment_id)
    if appt is None or appt.status != "scheduled":
        # Cancel any leftover schedule.
        await _cancel_apscheduler_jobs(scheduler, sj_repo, appointment_id)
        await sj_repo.replace_for_appointment(appointment_id, [])
        return

    tz: ZoneInfo = await settings_service.get_timezone(session)
    now_utc = _now_utc_naive()
    planned = await plan_jobs(session, appt, tz=tz, now_utc=now_utc)

    # Drop pre-existing APScheduler jobs we owned for this appointment.
    await _cancel_apscheduler_jobs(scheduler, sj_repo, appointment_id)

    new_rows: list[tuple[datetime, str, str | None]] = []
    for pj in planned:
        if pj.kind == "eve_digest":
            existing = await sj_repo.find_eve_digest_at(pj.fire_at_utc)
            if existing is not None and existing.appointment_id != appointment_id:
                # Dedup: another appointment already scheduled the same digest.
                # Reuse — no new APScheduler job, no DB row of our own.
                continue
        job_id: str | None = None
        if scheduler is not None and job_runner is not None:
            job_id = f"appt-{appointment_id}-{pj.kind}-{int(pj.fire_at_utc.timestamp())}"
            scheduler.add_job(
                job_runner,
                trigger="date",
                run_date=_ensure_utc_aware(pj.fire_at_utc),
                id=job_id,
                replace_existing=True,
                kwargs={
                    "appointment_id": appointment_id,
                    "kind": pj.kind,
                    "fire_at_utc_iso": pj.fire_at_utc.isoformat(),
                },
            )
        new_rows.append((pj.fire_at_utc, pj.kind, job_id))

    await sj_repo.replace_for_appointment(appointment_id, new_rows)


async def cancel_for_appointment(
    session: AsyncSession,
    *,
    scheduler: AsyncIOScheduler | None,
    appointment_id: int,
) -> None:
    """Drop every scheduled notification for the appointment — both the
    durable rows and the in-memory APScheduler jobs."""
    sj_repo = ScheduledJobRepository(session)
    await _cancel_apscheduler_jobs(scheduler, sj_repo, appointment_id)
    await sj_repo.replace_for_appointment(appointment_id, [])


async def _cancel_apscheduler_jobs(
    scheduler: AsyncIOScheduler | None,
    sj_repo: ScheduledJobRepository,
    appointment_id: int,
) -> None:
    if scheduler is None:
        return
    existing = await sj_repo.list_for_appointment(appointment_id)
    for row in existing:
        if not row.job_id:
            continue
        try:
            scheduler.remove_job(row.job_id)
        except Exception as exc:
            log.debug("apscheduler.remove_job(%s) failed: %s", row.job_id, exc)
