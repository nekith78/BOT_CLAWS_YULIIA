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
    denormalize_forms,
    detect_verb,
    extract_instagram,
    extract_name_candidate,
    extract_note,
    levenshtein,
    resolve_client_candidate,
)
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
