"""Tests for EditNoteAction."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.edit_note import EditNoteAction
from src.services.intent.types import ActionResult
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = EditNoteAction()
TZ = ZoneInfo("Asia/Almaty")


def _local_to_utc(d: date, hh: int, mm: int) -> datetime:
    return (
        datetime.combine(d, time(hh, mm), tzinfo=TZ)
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )


async def test_plan_fails_without_note(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "Ира", "note": "  "})
    assert resp.result is ActionResult.FAIL


async def test_plan_returns_confirm_with_note_payload(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира", "note": "френч"})

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload == {
        "appointment_id": appt.id,
        "note": "френч",
    }


async def test_plan_confirm_declares_note_editable_field(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    await AppointmentRepository(session).create(
        client_id=client.id,
        starts_at=_local_to_utc(date(2026, 5, 10), 11, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.plan(ctx, {"client_name": "Ира", "note": "френч"})

    assert resp.result is ActionResult.CONFIRM
    assert resp.editable_fields is not None
    assert len(resp.editable_fields) == 1
    field = resp.editable_fields[0]
    assert field.key == "note"
    assert field.editor == "text_input"
    assert field.prompt_text and "заметку" in field.prompt_text.lower()


async def test_plan_clarifies_when_client_name_empty_and_date_given(
    session: AsyncSession,
) -> None:
    """Plan #6 Layer A — «добавь заметку на 2026-05-08» without client → list
    appointments on that date and let user pick. note text is allowed to be
    empty here; the second brain handles missing-text via text-input."""
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
        starts_at=_local_to_utc(date(2026, 5, 8), 14, 0),
        duration_min=60,
    )

    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(
        ctx, {"client_name": "", "note": "", "date": "2026-05-08"}
    )

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2


async def test_plan_clarifies_when_client_name_empty_and_no_date(
    session: AsyncSession,
) -> None:
    irene = await ClientRepository(session).create(name="Ира")
    appt_repo = AppointmentRepository(session)
    await appt_repo.create(
        client_id=irene.id,
        starts_at=_local_to_utc(date(2026, 5, 9), 10, 0),
        duration_min=60,
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(ctx, {"client_name": "", "note": ""})

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None


async def test_execute_updates_visit_note(session: AsyncSession) -> None:
    client = await ClientRepository(session).create(name="Ира")
    appt = await AppointmentRepository(session).create(
        client_id=client.id, starts_at=_local_to_utc(date(2026, 5, 10), 11, 0), duration_min=60
    )
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))

    resp = await ACTION.execute(
        ctx, {"appointment_id": appt.id, "note": "гель-лак"}
    )

    assert resp.result is ActionResult.EXECUTED
    refreshed = await AppointmentRepository(session).get(appt.id)
    assert refreshed is not None
    assert refreshed.visit_note == "гель-лак"
