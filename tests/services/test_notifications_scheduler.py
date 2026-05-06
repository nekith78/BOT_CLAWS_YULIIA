"""Tests for scheduler bootstrap helpers + recovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import settings_service
from src.services.notifications.scheduler import (
    build_scheduler,
    recover_missed_jobs,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.scheduled_jobs import ScheduledJobRepository

TZ = ZoneInfo("Asia/Almaty")


def test_build_scheduler_returns_running_capable_instance() -> None:
    sched = build_scheduler("sqlite+aiosqlite:///./tmp_apsched_test.db")
    assert sched is not None
    # Should not raise — the call signature must accept this URL.


def _utc_naive_local(local_dt: datetime) -> datetime:
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_recover_overdue_marked_sent_without_message(
    session: AsyncSession,
) -> None:
    await settings_service.seed_defaults(session)
    client = await ClientRepository(session).create(name="A")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
    )
    sj_repo = ScheduledJobRepository(session)
    # 12 hours overdue → must be skipped.
    overdue_fire = _utc_naive_local(datetime(2026, 5, 6, 2, 0, tzinfo=TZ))
    await sj_repo.replace_for_appointment(
        appt.id, [(overdue_fire, "offset_ping", None)]
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    now_utc = _utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ))
    sent_late, skipped = await recover_missed_jobs(
        session, bot=bot, owner_chat_id=1, tz=TZ, now_utc=now_utc
    )
    assert (sent_late, skipped) == (0, 1)
    bot.send_message.assert_not_called()
    rows = await sj_repo.list_for_appointment(appt.id)
    assert rows[0].sent_at is not None


@pytest.mark.asyncio
async def test_recover_due_in_window_sends_late_message(
    session: AsyncSession,
) -> None:
    await settings_service.seed_defaults(session)
    client = await ClientRepository(session).create(name="Олег")
    appt = await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_utc_naive_local(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
        visit_note="маникюр",
    )
    sj_repo = ScheduledJobRepository(session)
    # 30 min ago → due within 6h window.
    due_fire = _utc_naive_local(datetime(2026, 5, 6, 13, 0, tzinfo=TZ))
    await sj_repo.replace_for_appointment(
        appt.id, [(due_fire, "offset_ping", None)]
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    now_utc = _utc_naive_local(datetime(2026, 5, 6, 13, 30, tzinfo=TZ))
    sent_late, skipped = await recover_missed_jobs(
        session, bot=bot, owner_chat_id=42, tz=TZ, now_utc=now_utc
    )
    assert (sent_late, skipped) == (1, 0)
    bot.send_message.assert_awaited_once()
    sent_text = bot.send_message.await_args.kwargs["text"]
    assert "(с задержкой)" in sent_text
    assert "Олег" in sent_text and "маникюр" in sent_text

    # Row marked sent → second recovery is a no-op.
    sent_late_2, skipped_2 = await recover_missed_jobs(
        session, bot=bot, owner_chat_id=42, tz=TZ,
        now_utc=now_utc + timedelta(minutes=1),
    )
    assert (sent_late_2, skipped_2) == (0, 0)
