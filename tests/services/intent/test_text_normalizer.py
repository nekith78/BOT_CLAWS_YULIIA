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

from src.services.intent.text_normalizer import detect_verb


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
