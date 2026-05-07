"""Tests for CreateAppointmentAction."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.actions.create_appointment import CreateAppointmentAction
from src.services.intent.types import ActionResult
from src.storage.models import Appointment
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from tests.services.intent.actions.conftest import build_ctx

ACTION = CreateAppointmentAction()


# --- plan() ---------------------------------------------------------------


async def test_plan_fails_when_name_missing(session: AsyncSession) -> None:
    ctx = build_ctx(session)
    resp = await ACTION.plan(
        ctx, {"client_name": "  ", "date": "2026-05-08", "time": "14:00"}
    )
    assert resp.result is ActionResult.FAIL


async def test_plan_fails_when_date_or_time_missing(session: AsyncSession) -> None:
    ctx = build_ctx(session)
    resp = await ACTION.plan(ctx, {"client_name": "Ира", "date": "2026-05-08"})
    assert resp.result is ActionResult.FAIL


async def test_plan_fails_for_past_datetime(session: AsyncSession) -> None:
    ctx = build_ctx(session, now_local=datetime(2026, 5, 7, 12, 0))
    resp = await ACTION.plan(
        ctx,
        {"client_name": "Ира", "date": "2026-05-06", "time": "10:00"},
    )
    assert resp.result is ActionResult.FAIL
    assert "прошл" in resp.text.lower()


async def test_plan_returns_confirm_for_new_client(session: AsyncSession) -> None:
    ctx = build_ctx(session)

    resp = await ACTION.plan(
        ctx,
        {
            "client_name": "Олег",
            "date": "2026-05-10",
            "time": "11:00",
            "instagram": "oleg_nails",
        },
    )

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload is not None
    assert resp.pending_payload["client_id"] is None
    assert resp.pending_payload["client_name"] == "Олег"
    assert resp.pending_payload["instagram"] == "oleg_nails"
    assert "новый клиент" in resp.text


async def test_plan_returns_confirm_for_existing_unique_client(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    ctx = build_ctx(session)

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "date": "2026-05-10", "time": "11:00"}
    )

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload is not None
    assert resp.pending_payload["client_id"] == client.id
    assert "Ира" in resp.text


async def test_plan_confirm_declares_editable_fields(
    session: AsyncSession,
) -> None:
    """CONFIRM card should expose 5 per-field edit buttons: client,
    date, time, note, instagram. Each with the right editor type so
    the intake handler dispatches to the right sub-flow."""
    await ClientRepository(session).create(name="Ира")
    ctx = build_ctx(session)

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "date": "2026-05-10", "time": "11:00"}
    )

    assert resp.result is ActionResult.CONFIRM
    assert resp.editable_fields is not None
    by_key = {f.key: f for f in resp.editable_fields}
    assert set(by_key) == {"client_name", "date", "time", "note", "instagram"}
    assert by_key["client_name"].editor == "client_picker"
    assert by_key["date"].editor == "calendar"
    assert by_key["time"].editor == "time_picker"
    assert by_key["note"].editor == "text_input"
    assert by_key["note"].prompt_text and "Напиши" in by_key["note"].prompt_text
    assert by_key["instagram"].editor == "text_input"


async def test_plan_fail_or_clarify_responses_have_no_editable_fields(
    session: AsyncSession,
) -> None:
    """FAIL/CLARIFY don't show a confirm-card, so editable_fields stays None."""
    ctx = build_ctx(session)
    resp_fail = await ACTION.plan(
        ctx, {"client_name": "  ", "date": "2026-05-10", "time": "14:00"}
    )
    assert resp_fail.result is ActionResult.FAIL
    assert resp_fail.editable_fields is None

    repo = ClientRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Ира")
    resp_clarify = await ACTION.plan(
        ctx, {"client_name": "Ира", "date": "2026-05-10", "time": "11:00"}
    )
    assert resp_clarify.result is ActionResult.CLARIFY
    assert resp_clarify.editable_fields is None


async def test_plan_returns_clarify_for_multiple_matching_clients(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    ira1 = await repo.create(name="Ира", instagram="ira_nails")
    ira2 = await repo.create(name="Ира")
    ctx = build_ctx(session)

    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "date": "2026-05-10", "time": "11:00"}
    )

    assert resp.result is ActionResult.CLARIFY
    assert resp.clarify_options is not None
    assert len(resp.clarify_options) == 2
    payloads = [opt.payload for opt in resp.clarify_options]
    assert {"client_id": ira1.id} in payloads
    assert {"client_id": ira2.id} in payloads
    labels = [opt.label for opt in resp.clarify_options]
    assert any("@ira_nails" in label for label in labels)


async def test_plan_uses_client_id_hint_skipping_resolve(
    session: AsyncSession,
) -> None:
    """After CLARIFY user picks one Ира — handler re-calls plan with client_id."""
    repo = ClientRepository(session)
    ira_picked = await repo.create(name="Ира", instagram="ira_picked")
    await repo.create(name="Ира")  # the unpicked one
    ctx = build_ctx(session)

    resp = await ACTION.plan(
        ctx,
        {
            "client_name": "Ира",
            "date": "2026-05-10",
            "time": "11:00",
            "client_id": ira_picked.id,
        },
    )

    assert resp.result is ActionResult.CONFIRM
    assert resp.pending_payload is not None
    assert resp.pending_payload["client_id"] == ira_picked.id


async def test_plan_fails_when_existing_client_has_overlap(
    session: AsyncSession,
) -> None:
    """If the slot is already occupied (any client), refuse."""
    repo = ClientRepository(session)
    ira = await repo.create(name="Ира")
    other = await repo.create(name="Олег")

    starts_at = datetime(2026, 5, 10, 6, 0)  # 11:00 Almaty in UTC (-5)
    await AppointmentRepository(session).create(
        client_id=other.id, starts_at=starts_at, duration_min=60
    )

    ctx = build_ctx(session)
    resp = await ACTION.plan(
        ctx, {"client_name": "Ира", "date": "2026-05-10", "time": "11:00"}
    )

    assert resp.result is ActionResult.FAIL
    assert "уже есть" in resp.text.lower() or "занят" in resp.text.lower()
    # Sanity — Ира exists, just couldn't be booked due to overlap.
    assert ira.id is not None


# --- execute() ------------------------------------------------------------


async def test_execute_creates_appointment_for_existing_client(
    session: AsyncSession,
) -> None:
    client = await ClientRepository(session).create(name="Ира")
    ctx = build_ctx(session)

    starts_at_utc = datetime(2026, 5, 10, 6, 0)  # 11:00 Almaty
    payload = {
        "client_id": client.id,
        "client_name": "Ира",
        "instagram": None,
        "starts_at_utc_iso": starts_at_utc.isoformat(),
        "note": "френч",
    }
    resp = await ACTION.execute(ctx, payload)

    assert resp.result is ActionResult.EXECUTED
    appts = await AppointmentRepository(session).list_for_client(client.id)
    assert len(appts) == 1
    assert appts[0].visit_note == "френч"


async def test_execute_creates_new_client_when_client_id_is_none(
    session: AsyncSession,
) -> None:
    ctx = build_ctx(session)

    payload = {
        "client_id": None,
        "client_name": "Олег",
        "instagram": "oleg_nails",
        "starts_at_utc_iso": datetime(2026, 5, 10, 6, 0).isoformat(),
        "note": None,
    }
    resp = await ACTION.execute(ctx, payload)

    assert resp.result is ActionResult.EXECUTED
    matches = await ClientRepository(session).search_by_name("Олег")
    assert len(matches) == 1
    assert matches[0].instagram == "oleg_nails"
    appts = await AppointmentRepository(session).list_for_client(matches[0].id)
    assert len(appts) == 1
    assert isinstance(appts[0], Appointment)
    # Sanity — UTC stored datetime matches the ISO we passed.
    assert appts[0].starts_at == datetime(2026, 5, 10, 6, 0)
