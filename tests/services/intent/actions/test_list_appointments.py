"""Tests for ListAppointmentsAction."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.list_appointments import ListAppointmentsAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = ListAppointmentsAction()
TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


async def test_today_returns_only_todays_appointments(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    today = date(2026, 5, 7)
    tomorrow = date(2026, 5, 8)

    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today, 11, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(tomorrow, 11, 0),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(today.year, today.month, today.day, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "today"})

    assert resp.result is ActionResult.EXECUTED
    assert "Сегодня" in resp.text
    assert resp.keyboard is not None
    assert len(resp.keyboard.inline_keyboard) == 1
    assert "Ира" in resp.keyboard.inline_keyboard[0][0].text


async def test_empty_period_returns_text_only(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "tomorrow"})

    assert resp.result is ActionResult.EXECUTED
    assert "Записей нет" in resp.text
    assert resp.keyboard is None


async def test_date_period_with_anchor(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    target = date(2026, 5, 15)
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(target, 14, 30),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "date", "date": "2026-05-15"})

    assert resp.result is ActionResult.EXECUTED
    assert resp.keyboard is not None
    assert any(
        "14:30" in row[0].text for row in resp.keyboard.inline_keyboard
    )


async def test_date_period_without_anchor_fails(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "date"})
    assert resp.result is ActionResult.FAIL


async def test_unknown_period_fails(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "yesterday"})
    assert resp.result is ActionResult.FAIL


async def test_week_groups_by_day(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    today = date(2026, 5, 7)
    later = today + timedelta(days=2)

    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today, 11, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(later, 14, 30),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(today.year, today.month, today.day, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "week"})

    assert resp.result is ActionResult.EXECUTED
    # Week header includes a date range; both appointments rendered.
    assert "Неделя" in resp.text
    assert resp.keyboard is not None
    assert len(resp.keyboard.inline_keyboard) == 2


async def test_today_attaches_context_snapshot_for_followups(
    session: AsyncSession,
) -> None:
    """After a list result, the action stashes appointments in
    `context_snapshot` so the intake handler can inject them into the
    next LLM prompt as «recently shown items»."""
    client = await ClientRepository(session).create(name="Костя")
    appt_repo = AppointmentRepository(session)
    today = date(2026, 5, 7)
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today, 11, 0),
        duration_min=60,
        visit_note="френч",
    )

    ctx = build_ctx(session, now_local=datetime(today.year, today.month, today.day, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "today"})

    assert resp.result is ActionResult.EXECUTED
    assert resp.context_snapshot is not None
    items = resp.context_snapshot["appointments"]
    assert len(items) == 1
    assert items[0]["client_name"] == "Костя"
    assert items[0]["time"] == "11:00"
    assert items[0]["note"] == "френч"


async def test_all_period_excludes_past(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    yesterday = date(2026, 5, 6)
    next_week = date(2026, 5, 14)

    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(yesterday, 11, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(next_week, 11, 0),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await ACTION.plan(ctx, {"period": "all"})

    assert resp.result is ActionResult.EXECUTED
    assert "Все будущие записи" in resp.text
    assert resp.keyboard is not None
    assert len(resp.keyboard.inline_keyboard) == 1
