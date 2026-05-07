"""Tests for the three read-only count_* actions."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.count_appointments import CountAppointmentsAction
from src.services.intent.actions.count_client_appointments import (
    CountClientAppointmentsAction,
)
from src.services.intent.actions.count_clients import CountClientsAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


# --- count_clients --------------------------------------------------------


async def test_count_clients_zero(session: AsyncSession) -> None:
    ctx = build_ctx(session)
    resp = await CountClientsAction().plan(ctx, {})
    assert resp.result is ActionResult.EXECUTED
    assert "0" in resp.text


async def test_count_clients_three(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    for name in ("Ира", "Олег", "Маша"):
        await repo.create(name=name)
    ctx = build_ctx(session)
    resp = await CountClientsAction().plan(ctx, {})
    assert "3" in resp.text
    # Russian declension — 3 → «клиента».
    assert "клиента" in resp.text


# --- count_appointments ---------------------------------------------------


async def test_count_appointments_today(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    repo = AppointmentRepository(session)
    today = date(2026, 5, 7)
    tomorrow = date(2026, 5, 8)
    await repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today, 11, 0),
        duration_min=60,
    )
    await repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(today, 14, 0),
        duration_min=60,
    )
    await repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(tomorrow, 11, 0),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await CountAppointmentsAction().plan(ctx, {"period": "today"})
    assert resp.result is ActionResult.EXECUTED
    assert "2" in resp.text


async def test_count_appointments_unknown_period_fails(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await CountAppointmentsAction().plan(ctx, {"period": "yesterday"})
    assert resp.result is ActionResult.FAIL


# --- count_client_appointments --------------------------------------------


async def test_count_client_appointments_returns_count(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    repo = AppointmentRepository(session)
    await repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 10), 11, 0),
        duration_min=60,
    )
    await repo.create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 12), 14, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))

    resp = await CountClientAppointmentsAction().plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.EXECUTED
    assert "2" in resp.text


async def test_count_client_appointments_clarifies_multiple_clients(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Ира", instagram="ira_nails")
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))

    resp = await CountClientAppointmentsAction().plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2
