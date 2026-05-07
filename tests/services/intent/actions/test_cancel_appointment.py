"""Tests for CancelAppointmentAction."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.cancel_appointment import CancelAppointmentAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = CancelAppointmentAction()
TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


async def test_plan_returns_confirm_for_single_appointment(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира"})

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload == {"appointment_id": appt.id}


async def test_plan_fails_when_no_client(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Олег"})
    assert resp.result is ActionResult.FAIL


async def test_plan_clarifies_multiple_appointments(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 12), 14, 0), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Ира"})

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2


async def test_cancel_confirm_has_no_editable_fields(session: AsyncSession) -> None:
    """cancel doesn't expose any per-field edit (only the binary
    confirm/cancel choice)."""
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 10), 11, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.CONFIRM
    assert resp.editable_fields is None


async def test_execute_marks_appointment_cancelled(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.execute(ctx, {"appointment_id": appt.id})

    assert resp.result is ActionResult.EXECUTED
    refreshed = await AppointmentRepository(session).get(appt.id)
    assert refreshed is not None
    assert refreshed.status == "cancelled"
