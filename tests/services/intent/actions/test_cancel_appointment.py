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


async def test_plan_clarifies_when_client_name_empty_and_date_given(
    session: AsyncSession,
) -> None:
    """Plan #6 Layer A — «отмени запись на 2026-05-08» without client_name
    must list the appointments on that date instead of FAILing."""
    irene = await ClientRepository(session).create(name="Ира")
    masha = await ClientRepository(session).create(name="Маша")
    olya = await ClientRepository(session).create(name="Оля")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=irene.id,
        starts_at=_local_to_utc(date(2026, 5, 8), 10, 0),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=masha.id,
        starts_at=_local_to_utc(date(2026, 5, 8), 14, 30),
        duration_min=60,
    )
    await appt_repo.create(
        client_id=olya.id,
        starts_at=_local_to_utc(date(2026, 5, 8), 18, 0),
        duration_min=60,
    )
    # An appointment on a different date — must NOT appear.
    await appt_repo.create(
        client_id=irene.id,
        starts_at=_local_to_utc(date(2026, 5, 9), 10, 0),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "", "date": "2026-05-08"})

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 3
    labels = [o.label for o in resp.clarify_options]
    assert any("Ира" in label and "10:00" in label for label in labels)
    assert any("Маша" in label and "14:30" in label for label in labels)
    assert any("Оля" in label and "18:00" in label for label in labels)
    # Each option carries an appointment_id payload patch.
    for opt in resp.clarify_options:
        assert "appointment_id" in opt.payload


async def test_plan_clarifies_when_client_name_empty_and_no_date(
    session: AsyncSession,
) -> None:
    """Plan #6 Layer A — «отмени запись» (no date, no name) lists upcoming."""
    irene = await ClientRepository(session).create(name="Ира")
    masha = await ClientRepository(session).create(name="Маша")
    appt_repo = AppointmentRepository(session)
    # Past appt — must NOT appear.
    await appt_repo.create(
        client_id=irene.id,
        starts_at=_local_to_utc(date(2026, 5, 1), 10, 0),
        duration_min=60,
    )
    # 5 future appts — all should appear (limit ≥ 5).
    for d, hh in [(8, 10), (9, 14), (10, 16), (11, 11), (12, 9)]:
        await appt_repo.create(
            client_id=masha.id,
            starts_at=_local_to_utc(date(2026, 5, d), hh, 0),
            duration_min=60,
        )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": ""})

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 5


async def test_plan_fails_when_client_name_empty_and_no_appointments_on_date(
    session: AsyncSession,
) -> None:
    """Layer A doesn't paper over the «no records at all» case — that's a
    legitimate FAIL and should stay one."""
    irene = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=irene.id,
        starts_at=_local_to_utc(date(2026, 5, 9), 10, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "", "date": "2026-05-08"})
    assert resp.result is ActionResult.FAIL


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
