"""Tests for DeleteClientAction."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.delete_client import DeleteClientAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = DeleteClientAction()
TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


async def test_plan_returns_confirm_with_appointment_warning(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира"})

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload == {"client_id": client.id}
    assert "1 активных" in resp.text or "удалятся" in resp.text


async def test_plan_fails_when_client_not_found(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Олег"})
    assert resp.result is ActionResult.FAIL


async def test_plan_clarifies_multiple_clients(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира", instagram="ira_a")
    await repo.create(name="Ира", instagram="ira_b")
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2


async def test_execute_deletes_client(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.execute(ctx, {"client_id": client.id})

    assert resp.result is ActionResult.EXECUTED
    assert await ClientRepository(session).get(client.id) is None
