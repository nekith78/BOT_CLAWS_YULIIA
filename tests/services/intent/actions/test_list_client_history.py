"""Tests for ListClientHistoryAction."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.list_client_history import ListClientHistoryAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = ListClientHistoryAction()
TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


async def test_returns_empty_history_message(session: AsyncSession) -> None:
    await ClientRepository(session).create(name="Ира")
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.EXECUTED
    assert "Записей нет" in resp.text
    assert resp.keyboard is None


async def test_returns_history_with_buttons(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 1), 11, 0), duration_min=60
    )
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 14, 0), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Ира"})

    assert resp.result is ActionResult.EXECUTED
    assert resp.keyboard is not None
    assert len(resp.keyboard.inline_keyboard) == 2


async def test_no_match_fails(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Олег"})
    assert resp.result is ActionResult.FAIL


async def test_clarifies_multiple_clients(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Ира", instagram="ira_nails")
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2
