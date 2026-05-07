"""Tests for MoveAppointmentAction."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.move_appointment import MoveAppointmentAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = MoveAppointmentAction()
TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


async def test_plan_fails_without_new_date_or_time(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Ира"})
    assert resp.result is ActionResult.FAIL


async def test_plan_fails_when_client_not_found(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(
        ctx, {"client_name": "Олег", "new_date": "2026-05-10", "new_time": "16:00"}
    )
    assert resp.result is ActionResult.FAIL
    assert "не нашёл" in resp.text.lower()


async def test_plan_returns_clarify_for_multiple_clients(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    ira1 = await repo.create(name="Ира")
    ira2 = await repo.create(name="Ира")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=ira1.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    await appt_repo.create(
        client_id=ira2.id, starts_at=_local_to_utc(date(2026, 5, 10), 12, 0), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "new_date": "2026-05-12", "new_time": "16:00"}
    )
    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2


async def test_plan_returns_clarify_for_multiple_appointments(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 8), 11, 0), duration_min=60
    )
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 12), 14, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "new_date": "2026-05-15", "new_time": "16:00"}
    )
    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2


async def test_plan_returns_confirm_for_single_appointment(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "new_time": "14:00"}
    )

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload is not None
    assert resp.pending_payload["appointment_id"] == appt.id
    new_starts = datetime.fromisoformat(resp.pending_payload["new_starts_at_utc_iso"])
    assert new_starts == _local_to_utc(date(2026, 5, 10), 14, 0)


async def test_plan_fails_for_past_target(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "new_date": "2026-05-05", "new_time": "11:00"}
    )
    assert resp.result is ActionResult.FAIL
    assert "прошлом" in resp.text.lower()


async def test_plan_fails_when_target_overlaps_other_booking(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    other = await ClientRepository(session).create(name="Олег")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    await appt_repo.create(
        client_id=other.id, starts_at=_local_to_utc(date(2026, 5, 10), 14, 0), duration_min=60
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "new_date": "2026-05-10", "new_time": "14:00"}
    )
    assert resp.result is ActionResult.FAIL
    assert "уже" in resp.text.lower()


async def test_plan_confirm_declares_two_editable_fields(
    session: AsyncSession,
) -> None:
    """Move CONFIRM should expose new_date + new_time edit buttons.
    Source-appointment identity is fixed at confirm time."""
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 10), 11, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "new_time": "14:00"}
    )

    assert resp.result is ActionResult.CONFIRM
    assert resp.editable_fields is not None
    keys = [f.key for f in resp.editable_fields]
    assert keys == ["new_date", "new_time"]
    editors = {f.key: f.editor for f in resp.editable_fields}
    assert editors["new_date"] == "calendar"
    assert editors["new_time"] == "time_picker"


async def test_execute_reschedules_appointment(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    new_at = _local_to_utc(date(2026, 5, 10), 14, 0)
    resp = await ACTION.execute(
        ctx,
        {
            "appointment_id": appt.id,
            "new_starts_at_utc_iso": new_at.isoformat(),
        },
    )
    assert resp.result is ActionResult.EXECUTED

    refreshed = await AppointmentRepository(session).get(appt.id)
    assert refreshed is not None
    assert refreshed.starts_at == new_at


async def test_plan_clarifies_when_client_name_empty(session: AsyncSession) -> None:
    """Plan #6 Layer A — «перенеси на 16:00» without client_name → list
    upcoming appointments and let user pick the source one."""
    irene = await ClientRepository(session).create(name="Ира")
    masha = await ClientRepository(session).create(name="Маша")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=irene.id,
        starts_at=_local_to_utc(date(2026, 5, 8), 10, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=masha.id,
        starts_at=_local_to_utc(date(2026, 5, 9), 14, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(
        ctx, {"client_name": "", "new_time": "16:00"}
    )

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2
    for opt in resp.clarify_options:
        assert "appointment_id" in opt.payload
