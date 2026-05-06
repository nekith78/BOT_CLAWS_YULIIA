"""APScheduler bootstrap + job runner + startup recovery.

`build_scheduler` returns an AsyncIOScheduler with a SQLAlchemyJobStore
on the same SQLite file used by the bot. Jobs survive a restart.

`make_job_runner` returns the awaitable callable APScheduler invokes
when a fire_at moment arrives. The runner is wired into the dispatcher
data dict (`notify_runner`) so handlers can pass it to
`reschedule_for_appointment`.

`recover_missed_jobs` walks the durable scheduled_jobs at startup and
either re-sends them with a late prefix (≤6h overdue) or marks them
sent (>6h overdue → skip).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.services import settings_service
from src.services.notifications.senders import (
    send_eve_digest,
    send_offset_ping,
)
from src.storage.db import session_scope
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.scheduled_jobs import ScheduledJobRepository

log = logging.getLogger(__name__)


def build_scheduler(db_url: str) -> AsyncIOScheduler:
    """Async scheduler with persistent jobstore on the same SQLite DB.

    aiosqlite is async-only; APScheduler's jobstore needs a sync URL.
    Strip the `+aiosqlite` driver tag.
    """
    sync_url = db_url.replace("+aiosqlite", "")
    scheduler = AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=sync_url)},
        timezone=timezone.utc,
    )
    return scheduler


def make_job_runner(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    owner_chat_id: int,
) -> Any:
    """Return the awaitable APScheduler will invoke at fire_at.

    The closure binds the dependencies a job needs at execution time
    (bot client, DB session factory, owner chat id). Stored in the
    APScheduler jobstore via reference, so the function path must be
    importable on restart.
    """

    async def _runner(
        *, appointment_id: int, kind: str, fire_at_utc_iso: str
    ) -> None:
        log.info(
            "notify-job fired: appt=%s kind=%s fire_at=%s",
            appointment_id, kind, fire_at_utc_iso,
        )
        async with session_scope(session_factory) as session:
            tz = await settings_service.get_timezone(session)
            await _dispatch_job(
                session,
                bot=bot,
                owner_chat_id=owner_chat_id,
                tz=tz,
                appointment_id=appointment_id,
                kind=kind,
                fire_at_utc_iso=fire_at_utc_iso,
                late=False,
            )

    return _runner


async def _dispatch_job(
    session: AsyncSession,
    *,
    bot: Bot,
    owner_chat_id: int,
    tz: ZoneInfo,
    appointment_id: int,
    kind: str,
    fire_at_utc_iso: str,
    late: bool,
) -> None:
    """Look up scheduled_job row, fire it, mark sent. Idempotent —
    if the row is already sent or missing, no-op."""
    sj_repo = ScheduledJobRepository(session)
    appt_repo = AppointmentRepository(session)
    client_repo = ClientRepository(session)

    fire_at = datetime.fromisoformat(fire_at_utc_iso)
    if fire_at.tzinfo is not None:
        fire_at = fire_at.astimezone(timezone.utc).replace(tzinfo=None)

    if kind == "eve_digest":
        # Find target date = day-of(fire_at + 1d) in OWNER_TZ.
        from datetime import time, timedelta

        fire_local = fire_at.replace(tzinfo=timezone.utc).astimezone(tz)
        target_date = fire_local.date() + timedelta(days=1)
        start_local = datetime.combine(target_date, time(0), tzinfo=tz)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
        appts = await appt_repo.list_in_range(start=start_utc, end=end_utc)
        pairs = []
        for a in appts:
            c = await client_repo.get(a.client_id)
            if c is not None:
                pairs.append((a, c))
        await send_eve_digest(bot, owner_chat_id, pairs, tz=tz, late=late)
    elif kind == "offset_ping":
        appt = await appt_repo.get(appointment_id)
        if appt is None or appt.status != "scheduled":
            log.info("offset_ping skip: appt %s gone or not scheduled", appointment_id)
        else:
            client = await client_repo.get(appt.client_id)
            if client is not None:
                await send_offset_ping(
                    bot, owner_chat_id, appt, client, tz=tz, late=late
                )
    else:
        log.warning("unknown notify kind: %s", kind)
        return

    # Find the matching scheduled_job row for this fire_at and mark it sent.
    rows = await sj_repo.list_for_appointment(appointment_id)
    for row in rows:
        if row.kind == kind and row.fire_at == fire_at and row.sent_at is None:
            await sj_repo.mark_sent(
                row.id,
                when=datetime.now(tz=timezone.utc).replace(tzinfo=None),
            )
            return


async def recover_missed_jobs(
    session: AsyncSession,
    *,
    bot: Bot,
    owner_chat_id: int,
    tz: ZoneInfo,
    now_utc: datetime,
    max_age_hours: int = 6,
) -> tuple[int, int]:
    """Walk scheduled_jobs that the bot missed during downtime.

    Returns (sent_late_count, skipped_count).

    Within the window: send late, mark sent_at.
    Beyond the window: just mark sent_at (skip).
    """
    sj_repo = ScheduledJobRepository(session)

    overdue = await sj_repo.list_overdue_to_skip(now=now_utc, max_age_hours=max_age_hours)
    skipped = 0
    for row in overdue:
        await sj_repo.mark_sent(row.id, when=now_utc)
        skipped += 1

    due = await sj_repo.list_due_unsent(now=now_utc, max_age_hours=max_age_hours)
    sent_late = 0
    for row in due:
        await _dispatch_job(
            session,
            bot=bot,
            owner_chat_id=owner_chat_id,
            tz=tz,
            appointment_id=row.appointment_id,
            kind=row.kind,
            fire_at_utc_iso=row.fire_at.isoformat(),
            late=True,
        )
        sent_late += 1

    return (sent_late, skipped)
