"""Tests for the three bulk-destructive actions.

Each action's plan() must show a CONFIRM card with the full list of
items it would touch (safety preview). execute() must be idempotent —
records that became no-longer-«scheduled» between plan and execute are
silently skipped.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.bulk_cancel_by_client import BulkCancelByClientAction
from src.services.intent.actions.bulk_cancel_by_date import BulkCancelByDateAction
from src.services.intent.actions.bulk_delete_clients import BulkDeleteClientsAction
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


# --- bulk_cancel_by_date --------------------------------------------------


async def test_bulk_cancel_by_date_confirm_lists_all_appointments(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    repo = AppointmentRepository(session)
    target = date(2026, 5, 10)
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(target, 11, 0), duration_min=60
    )
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(target, 14, 30), duration_min=60
    )
    # Different day — must not be touched.
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 11), 11, 0), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await BulkCancelByDateAction().plan(ctx, {"date": "2026-05-10"})

    assert resp.result is ActionResult.CONFIRM
    assert "2 записей" in resp.text
    assert resp.pending_payload is not None
    assert len(resp.pending_payload["appointment_ids"]) == 2


async def test_bulk_cancel_by_date_empty_day_fails(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await BulkCancelByDateAction().plan(ctx, {"date": "2026-05-10"})
    assert resp.result is ActionResult.FAIL


async def test_bulk_cancel_by_date_execute_marks_each_cancelled(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    repo = AppointmentRepository(session)
    target = date(2026, 5, 10)
    appt1 = await repo.create(
        client_id=client.id, starts_at=_local_to_utc(target, 11, 0), duration_min=60
    )
    appt2 = await repo.create(
        client_id=client.id, starts_at=_local_to_utc(target, 14, 30), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await BulkCancelByDateAction().execute(
        ctx, {"date": "2026-05-10", "appointment_ids": [appt1.id, appt2.id]}
    )
    assert resp.result is ActionResult.EXECUTED
    assert "Отменено 2 из 2" in resp.text

    refreshed1 = await repo.get(appt1.id)
    refreshed2 = await repo.get(appt2.id)
    assert refreshed1 is not None and refreshed1.status == "cancelled"
    assert refreshed2 is not None and refreshed2.status == "cancelled"


# --- bulk_cancel_by_client ------------------------------------------------


async def test_bulk_cancel_by_client_lists_only_future(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    repo = AppointmentRepository(session)
    # Past — must not be touched.
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 1), 11, 0), duration_min=60
    )
    # Future.
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 12), 14, 0), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))
    resp = await BulkCancelByClientAction().plan(ctx, {"client_name": "Ира"})

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload is not None
    assert len(resp.pending_payload["appointment_ids"]) == 2


async def test_bulk_cancel_by_client_clarifies_multiple_clients(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Ира", instagram="ira_nails")
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))

    resp = await BulkCancelByClientAction().plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.CLARIFY


async def test_bulk_cancel_by_client_no_future_fails(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    repo = AppointmentRepository(session)
    await repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 1), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 9, 0))

    resp = await BulkCancelByClientAction().plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.FAIL


# --- bulk_delete_clients --------------------------------------------------


async def test_bulk_delete_clients_empty_db_fails(session: AsyncSession) -> None:
    ctx = build_ctx(session)
    resp = await BulkDeleteClientsAction().plan(ctx, {})
    assert resp.result is ActionResult.FAIL


async def test_bulk_delete_clients_confirm_carries_explicit_warning(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Олег")
    ctx = build_ctx(session)

    resp = await BulkDeleteClientsAction().plan(ctx, {})
    assert resp.result is ActionResult.CONFIRM
    assert "ОПАСНО" in resp.text or "Опасно".upper() in resp.text
    assert "ОТМЕНИТЬ" in resp.text  # «ЭТО НЕЛЬЗЯ ОТМЕНИТЬ» warning
    assert "2" in resp.text  # client count


async def test_bulk_delete_clients_execute_drops_all_clients(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Олег")
    ctx = build_ctx(session)

    resp = await BulkDeleteClientsAction().execute(ctx, {})
    assert resp.result is ActionResult.EXECUTED

    matches = await repo.search_by_name("")
    # search_by_name with empty string returns [] guard — use list_recent.
    recent = await repo.list_recent(limit=10)
    assert recent == []
    _ = matches
