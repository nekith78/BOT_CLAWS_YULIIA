"""Unit tests for the smart-fallback text normalizer (second brain).

The normalizer is two pure functions plus helpers:
  - extract(text, today, repos) — runs ONCE on the raw transcript.
  - decide_next(entities, today, repos) — runs after extract and after
    every clarifying answer.

This file covers each surface separately. Storage-level fixtures are
shared with the action tests (`session`).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.intent.text_normalizer import (
    NormalizationResult,
    build_canonical,
    compute_missing,
    decide_next,
    denormalize_forms,
    detect_verb,
    extract,
    extract_instagram,
    extract_name_candidate,
    extract_note,
    levenshtein,
    resolve_client_candidate,
)
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


@pytest.mark.parametrize(
    "phrase, expected",
    [
        # create
        ("запиши Иру на завтра в 14", "create_appointment"),
        ("поставь Машу 16:30 на 8 мая", "create_appointment"),
        ("создай запись для Юли на пятницу", "create_appointment"),
        ("зафиксируй запись Ани на завтра", "create_appointment"),
        # cancel
        ("отмени завтрашнюю запись", "cancel_appointment"),
        ("отмени запись на 8 мая", "cancel_appointment"),
        ("сними запись Иры", "cancel_appointment"),
        # «удали Иру» — no «клиент» word, no «заметк» → cancel.
        ("удали Иру", "cancel_appointment"),
        # delete_client (must beat cancel because of «клиент»)
        ("удали клиента Машу", "delete_client"),
        ("удали клиента", "delete_client"),
        ("выкини клиента Олю", "delete_client"),
        # move
        ("перенеси Иру на 16", "move_appointment"),
        ("передвинь запись Маши на завтра в 14:30", "move_appointment"),
        ("переставь Аню на пятницу", "move_appointment"),
        # edit_note (note stem wins over create's «добавь»)
        ("добавь заметку Маше", "edit_note"),
        ("добавь заметку: френч с блёстками", "edit_note"),
        ("припиши Маше что ноготь треснул", "edit_note"),
        ("заметка: гель не держится", "edit_note"),
        # list_appointments
        ("покажи записи на завтра", "list_appointments"),
        ("какие у меня записи", "list_appointments"),
        ("список записей", "list_appointments"),
        # list_clients
        ("покажи клиентов", "list_clients"),
        ("список клиентов", "list_clients"),
        # negatives — too ambiguous or no verb at all
        ("привет, как дела", None),
        ("добавь Иру в клиенты", None),  # no matching verb path
        ("покажи Иру", None),  # no «запис» or «клиент»
        ("", None),
        ("16:30", None),
    ],
)
def test_detect_verb(phrase: str, expected: str | None) -> None:
    assert detect_verb(phrase) == expected


# --- extract_note ----------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected_note, expected_remainder",
    [
        # marker word inside a longer phrase
        (
            "запиши Иру на завтра 14 заметка френч",
            "френч",
            "запиши Иру на завтра 14",
        ),
        (
            "запиши Иру 14 заметка: френч с блёстками",
            "френч с блёстками",
            "запиши Иру 14",
        ),
        # «припиши Маше что ...» — the «что» after the marker is dropped.
        (
            "припиши Маше что ноготь треснул",
            "ноготь треснул",
            "Маше",
        ),
        # «с заметкой» phrasing
        (
            "поставь Юлю на 14 с заметкой гель не держится",
            "гель не держится",
            "поставь Юлю на 14",
        ),
        # No marker → returns (None, original).
        ("отмени завтрашнюю", None, "отмени завтрашнюю"),
        ("", None, ""),
    ],
)
def test_extract_note(
    phrase: str, expected_note: str | None, expected_remainder: str
) -> None:
    note, remainder = extract_note(phrase)
    assert note == expected_note
    assert remainder.strip() == expected_remainder.strip()


# --- extract_instagram -----------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected_handle, expected_remainder",
    [
        ("@ira_nails", "@ira_nails", ""),
        ("запиши Иру инстаграм @ira_nails", "@ira_nails", "запиши Иру"),
        ("запиши Иру инста ira_nails", "@ira_nails", "запиши Иру"),
        ("запиши Иру insta ira_nails", "@ira_nails", "запиши Иру"),
        ("запиши Иру", None, "запиши Иру"),
        ("", None, ""),
    ],
)
def test_extract_instagram(
    phrase: str, expected_handle: str | None, expected_remainder: str
) -> None:
    handle, remainder = extract_instagram(phrase)
    assert handle == expected_handle
    assert remainder.strip() == expected_remainder.strip()


# --- extract_name_candidate ------------------------------------------------


@pytest.mark.parametrize(
    "phrase, verb, expected",
    [
        ("запиши Иру на завтра в 14", "create_appointment", "Иру"),
        ("запиши Машу на 14:30", "create_appointment", "Машу"),
        # Skip the «запись» stop-word and pick the actual name.
        ("отмени запись Маши на завтра", "cancel_appointment", "Маши"),
        # Multi-word names — take everything until the next anchor.
        (
            "перенеси Анну Сергеевну на 16",
            "move_appointment",
            "Анну Сергеевну",
        ),
        # Anchor by date/time tokens, not just prepositions.
        ("отмени Иру 14:30", "cancel_appointment", "Иру"),
        # No name expected for list verbs.
        ("покажи записи на завтра", "list_appointments", None),
        ("покажи клиентов", "list_clients", None),
        # Empty / nothing useful.
        ("отмени завтрашнюю", "cancel_appointment", None),
        ("", "create_appointment", None),
    ],
)
def test_extract_name_candidate(
    phrase: str, verb: str, expected: str | None
) -> None:
    assert extract_name_candidate(phrase, verb) == expected


# --- denormalize_forms -----------------------------------------------------


@pytest.mark.parametrize(
    "candidate, expected_nom",
    [
        ("Иру", "Ира"),
        ("Машу", "Маша"),
        ("Юлю", "Юля"),
        ("Иры", "Ира"),
        ("Маши", "Маша"),
        ("Юли", "Юля"),
        ("Ире", "Ира"),
        ("Ира", "Ира"),  # already nominative — must still appear
        ("Маша", "Маша"),
    ],
)
def test_denormalize_forms_contains_expected(
    candidate: str, expected_nom: str
) -> None:
    forms = denormalize_forms(candidate)
    assert expected_nom in forms
    # The candidate as-is must always appear too — used as a fallback.
    assert candidate in forms


# --- levenshtein -----------------------------------------------------------


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("", "", 0),
        ("a", "a", 0),
        ("Ира", "Ира", 0),
        # single edits
        ("a", "ab", 1),  # insert
        ("ab", "a", 1),  # delete
        ("a", "b", 1),  # substitute
        ("Ира", "Ера", 1),
        ("Ира", "Ирa", 1),  # latin a swapped in
        # two-plus edits
        ("кот", "крот", 1),
        ("abc", "xyz", 3),
        ("Ира", "Юра", 1),  # И → Ю
    ],
)
def test_levenshtein(a: str, b: str, expected: int) -> None:
    assert levenshtein(a, b) == expected


# --- resolve_client_candidate (async, needs session) ----------------------


async def test_resolve_finds_via_denormalisation(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    ira = await repo.create(name="Ира")

    name, cid = await resolve_client_candidate("Иру", repo)
    assert name == "Ира"
    assert cid == ira.id


async def test_resolve_handles_masha(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    masha = await repo.create(name="Маша")

    name, cid = await resolve_client_candidate("Машу", repo)
    assert name == "Маша"
    assert cid == masha.id


async def test_resolve_uses_levenshtein_for_typos(session: AsyncSession) -> None:
    """«Ера» → «Ира» via Levenshtein ≤ 1 fallback."""
    repo = ClientRepository(session)
    ira = await repo.create(name="Ира")

    name, cid = await resolve_client_candidate("Ера", repo)
    assert name == "Ира"
    assert cid == ira.id


async def test_resolve_returns_first_form_when_db_empty(
    session: AsyncSession,
) -> None:
    repo = ClientRepository(session)
    name, cid = await resolve_client_candidate("Иру", repo)
    assert name == "Ира"
    assert cid is None


async def test_resolve_no_match_returns_first_form(session: AsyncSession) -> None:
    """DB has unrelated names; resolve returns the denormalised form (no id)
    so create_appointment can use it as a new-client name."""
    repo = ClientRepository(session)
    await repo.create(name="Аня")
    await repo.create(name="Юра")

    name, cid = await resolve_client_candidate("Юлю", repo)
    assert name == "Юля"
    assert cid is None


# --- compute_missing -------------------------------------------------------


@pytest.mark.parametrize(
    "verb, entities, expected_missing",
    [
        # create — needs name, date, time
        ("create_appointment", {"name": "Ира", "date": "2026-05-08", "time": "14:30"}, []),
        ("create_appointment", {"name": "Ира", "date": "2026-05-08"}, ["time"]),
        ("create_appointment", {"name": "Ира"}, ["date", "time"]),
        ("create_appointment", {}, ["name", "date", "time"]),
        # update_note — needs appointment_id + note_text
        ("edit_note", {"appointment_id": 42, "note_text": "френч"}, []),
        ("edit_note", {"appointment_id": 42}, ["note_text"]),
        ("edit_note", {}, ["appointment_ref", "note_text"]),
        # cancel — only appointment_ref
        ("cancel_appointment", {"appointment_id": 42}, []),
        ("cancel_appointment", {}, ["appointment_ref"]),
        # move — appointment_ref + (new_date OR new_time)
        ("move_appointment", {"appointment_id": 42, "new_time": "16:00"}, []),
        ("move_appointment", {"appointment_id": 42, "new_date": "2026-05-09"}, []),
        ("move_appointment", {"appointment_id": 42}, ["new_date_or_time"]),
        # delete_client — client_id only
        ("delete_client", {"client_id": 7}, []),
        ("delete_client", {}, ["client_id"]),
        # list_* — nothing required
        ("list_appointments", {}, []),
        ("list_clients", {}, []),
    ],
)
def test_compute_missing(
    verb: str, entities: dict[str, str | int], expected_missing: list[str]
) -> None:
    assert compute_missing(verb, entities) == expected_missing


# --- build_canonical -------------------------------------------------------


@pytest.mark.parametrize(
    "verb, entities, expected",
    [
        (
            "create_appointment",
            {"name": "Ира", "date": "2026-05-08", "time": "14:30"},
            "запиши Ира на 2026-05-08 в 14:30",
        ),
        (
            "create_appointment",
            {
                "name": "Ира",
                "date": "2026-05-08",
                "time": "14:30",
                "note": "френч",
            },
            "запиши Ира на 2026-05-08 в 14:30 с заметкой френч",
        ),
        (
            "create_appointment",
            {
                "name": "Ира",
                "date": "2026-05-08",
                "time": "14:30",
                "note": "френч",
                "instagram": "@ira_nails",
            },
            "запиши Ира на 2026-05-08 в 14:30 с заметкой френч инстаграм @ira_nails",
        ),
        (
            "cancel_appointment",
            {
                "name": "Ира",
                "date": "2026-05-08",
                "time": "14:00",
                "appointment_id": 42,
            },
            "отмени запись Ира 2026-05-08 14:00",
        ),
        (
            "move_appointment",
            {
                "name": "Ира",
                "date": "2026-05-08",
                "time": "14:00",
                "appointment_id": 42,
                "new_date": "2026-05-09",
                "new_time": "16:00",
            },
            "перенеси запись Ира 2026-05-08 14:00 на 2026-05-09 в 16:00",
        ),
        (
            "edit_note",
            {
                "name": "Ира",
                "date": "2026-05-08",
                "time": "14:00",
                "appointment_id": 42,
                "note_text": "френч",
            },
            "добавь к записи Ира 2026-05-08 14:00 заметку: френч",
        ),
        (
            "list_appointments",
            {"date": "2026-05-08"},
            "покажи записи на 2026-05-08",
        ),
        ("list_appointments", {}, "покажи все записи"),
        ("list_clients", {}, "покажи всех клиентов"),
        (
            "delete_client",
            {"name": "Ира", "client_id": 7},
            "удали клиента Ира",
        ),
    ],
)
def test_build_canonical(
    verb: str, entities: dict[str, str | int], expected: str
) -> None:
    assert build_canonical(verb, entities) == expected


# --- extract end-to-end ----------------------------------------------------


async def test_extract_full_create(session: AsyncSession) -> None:
    """Two-pass pipeline on a full create command."""
    repo = ClientRepository(session)
    await repo.create(name="Ира")
    appt_repo = AppointmentRepository(session)

    from datetime import date as _date
    today = _date(2026, 5, 7)
    entities = await extract(
        "запиши Иру на завтра в 14:30 заметка френч инстаграм @ira_nails",
        today,
        repo,
        appt_repo,
    )

    assert entities["verb"] == "create_appointment"
    assert entities["name"] == "Ира"
    assert entities["client_id"] is not None
    assert entities["date"] == "2026-05-08"
    assert entities["time"] == "14:30"
    assert entities["note"] == "френч"
    assert entities["instagram"] == "@ira_nails"


async def test_extract_no_verb(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    from datetime import date as _date
    entities = await extract("привет", _date(2026, 5, 7), repo, appt_repo)
    assert entities == {}


async def test_extract_cancel_partial(session: AsyncSession) -> None:
    """«отмени завтрашнюю» → verb + date, no name."""
    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    from datetime import date as _date
    entities = await extract(
        "отмени завтрашнюю запись", _date(2026, 5, 7), repo, appt_repo
    )
    assert entities["verb"] == "cancel_appointment"
    assert entities["date"] == "2026-05-08"
    assert entities.get("name") is None


# --- decide_next end-to-end ------------------------------------------------


async def test_decide_next_no_verb(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    from datetime import date as _date
    result = await decide_next({}, _date(2026, 5, 7), repo, appt_repo)
    assert result.kind == "no_verb_detected"


async def test_decide_next_canonical_ready(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    from datetime import date as _date
    entities = {
        "verb": "create_appointment",
        "name": "Ира",
        "date": "2026-05-08",
        "time": "14:30",
    }
    result = await decide_next(entities, _date(2026, 5, 7), repo, appt_repo)
    assert result.kind == "canonical_ready"
    assert result.canonical_text == "запиши Ира на 2026-05-08 в 14:30"


async def test_decide_next_clarifies_appointment_ref(session: AsyncSession) -> None:
    """Cancel without a known appointment, two candidates on date → CLARIFY."""
    from datetime import date as _date
    from datetime import datetime, timezone
    from datetime import time as _time
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Almaty")
    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)

    irene = await repo.create(name="Ира")
    masha = await repo.create(name="Маша")
    for d, hh in [(8, 10), (8, 14)]:
        local = datetime.combine(_date(2026, 5, d), _time(hh, 0), tzinfo=tz)
        utc = local.astimezone(timezone.utc).replace(tzinfo=None)
        await appt_repo.create(
            client_id=irene.id if hh == 10 else masha.id, starts_at=utc
        )

    entities = {
        "verb": "cancel_appointment",
        "date": "2026-05-08",
    }
    result = await decide_next(entities, _date(2026, 5, 7), repo, appt_repo)
    assert result.kind == "needs_clarification"
    assert result.question is not None
    assert result.question.field == "appointment_ref"
    assert result.question.editor == "appointment_picker"
    assert result.question.options is not None
    assert len(result.question.options) == 2


async def test_decide_next_asks_for_note_text(session: AsyncSession) -> None:
    """edit_note with appointment_id but no note_text → text-input question."""
    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    from datetime import date as _date
    entities = {"verb": "edit_note", "appointment_id": 42}
    result = await decide_next(entities, _date(2026, 5, 7), repo, appt_repo)
    assert result.kind == "needs_clarification"
    assert result.question is not None
    assert result.question.field == "note_text"
    assert result.question.editor == "text_input"


async def test_create_appointment_asks_existing_or_new_first(
    session: AsyncSession,
) -> None:
    """«создай запись на завтра» — name missing. We must NOT immediately
    list existing clients; first ask binary «existing or new?»."""
    from datetime import date as _date

    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    await repo.create(name="Ира")  # there ARE clients in DB; still ask choice

    entities = {"verb": "create_appointment", "date": "2026-05-09"}
    result = await decide_next(entities, _date(2026, 5, 8), repo, appt_repo)
    assert result.kind == "needs_clarification"
    assert result.question is not None
    assert result.question.field == "client_choice"
    assert result.question.editor == "client_choice"
    assert result.question.options is not None
    labels = [o.label for o in result.question.options]
    assert any("Из списка" in lbl for lbl in labels)
    assert any("Новый" in lbl for lbl in labels)


async def test_create_appointment_after_choice_existing_lists_clients(
    session: AsyncSession,
) -> None:
    from datetime import date as _date

    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)
    await repo.create(name="Ира")
    await repo.create(name="Маша")

    entities = {
        "verb": "create_appointment",
        "date": "2026-05-09",
        "client_choice": "existing",
    }
    result = await decide_next(entities, _date(2026, 5, 8), repo, appt_repo)
    assert result.kind == "needs_clarification"
    assert result.question is not None
    assert result.question.editor == "client_picker"
    assert result.question.options is not None
    assert {opt.label for opt in result.question.options} >= {"Ира", "Маша"}


async def test_create_appointment_after_choice_new_asks_for_name(
    session: AsyncSession,
) -> None:
    from datetime import date as _date

    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)

    entities = {
        "verb": "create_appointment",
        "date": "2026-05-09",
        "client_choice": "new",
    }
    result = await decide_next(entities, _date(2026, 5, 8), repo, appt_repo)
    assert result.kind == "needs_clarification"
    assert result.question is not None
    assert result.question.field == "name"
    assert result.question.editor == "text_input"
    assert "Имя" in result.question.prompt


async def test_create_appointment_existing_with_no_clients_falls_to_text_input(
    session: AsyncSession,
) -> None:
    """«Из списка» when DB is empty must NOT dead-end. Fall back to
    text-input so the user can still create the appointment."""
    from datetime import date as _date

    repo = ClientRepository(session)
    appt_repo = AppointmentRepository(session)

    entities = {
        "verb": "create_appointment",
        "date": "2026-05-09",
        "client_choice": "existing",
    }
    result = await decide_next(entities, _date(2026, 5, 8), repo, appt_repo)
    assert result.kind == "needs_clarification"
    assert result.question is not None
    assert result.question.editor == "text_input"


# Sanity — NormalizationResult is exposed.
def test_normalization_result_dataclass() -> None:
    r = NormalizationResult(kind="no_verb_detected")
    assert r.kind == "no_verb_detected"
    assert r.canonical_text is None
    assert r.question is None
