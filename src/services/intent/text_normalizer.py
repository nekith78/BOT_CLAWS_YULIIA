"""Smart-fallback "second brain" — text normalizer.

This module is the bot's local fallback when the LLM fails to pick a tool
on free-form input. It is NOT a parallel intent parser: it doesn't call
actions, doesn't construct args, doesn't know tool signatures. Instead it
extracts a verb and entities from raw Russian text, asks clarifying
questions when something required is missing, and finally builds a clean
canonical Russian sentence (`«запиши Ира на 2026-05-08 в 14:30»`) that
LLM #2 can tool-call on without ambiguity.

Two-stage entry: `extract()` runs once on the raw transcript, then
`decide_next()` runs after each user clarification answer. The bot owns
all FSM state; the normalizer is stateless.

Pure functions only — no aiogram imports, no LLM imports.
"""

from __future__ import annotations

import re

# --- vocabulary ------------------------------------------------------------
#
# Verb sets are matched as whole-word tokens against the lowercased text.
# Stems use substring search (`in lowered`) — this catches morphological
# variants like «записей / запись / записью» without listing every form.
#
# Order of detection in `detect_verb` follows priority rules from the
# spec §3.2 / §4.

_VERBS_CREATE = {
    "запиши",
    "запишу",
    "поставь",
    "поставлю",
    "создай",
    "зафиксируй",
    "добавь",
}
_VERBS_CANCEL = {"отмени", "удали", "сними", "убери"}
_VERBS_RESCHEDULE = {
    "перенеси",
    "передвинь",
    "сдвинь",
    "переставь",
    "измени",
}
_VERBS_LIST = {"покажи", "список", "какие", "кто"}

_STEM_NOTE = ("заметк", "пометк", "припиш", "допиш")

# `\b` (word boundary) makes sure we don't match «клиентский».
_CLIENT_RE = re.compile(r"\bклиент(а|ов|у|ы)?\b", re.IGNORECASE)
# Matches «запис|записи|записей|запись|записью» — stem-level.
_APPT_RE = re.compile(r"\bзапис\w*\b", re.IGNORECASE)


_TOKEN_RE = re.compile(r"\b\w+\b", re.UNICODE)


def _has_verb(tokens: set[str], verb_set: set[str]) -> bool:
    return bool(tokens & verb_set)


def detect_verb(text: str) -> str | None:
    """Match the user's phrase to one of the seven supported intents.

    Returns one of:
        "create_appointment", "cancel_appointment", "move_appointment",
        "edit_note", "list_appointments", "list_clients", "delete_client"
    or None if no rule matched.

    Priority (the first matching rule wins):
        1. `заметк` stem present       → edit_note
        2. verb in {удали, выкини, убери} AND «клиент» → delete_client
        3. verb in {покажи, список, какие, кто}:
            - «клиент» in text → list_clients
            - «запис»  in text → list_appointments
        4. verb in CREATE set          → create_appointment
        5. verb in CANCEL set          → cancel_appointment
        6. verb in RESCHEDULE set      → move_appointment
        7. otherwise                   → None
    """
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    tokens = set(_TOKEN_RE.findall(cleaned))

    # Rule 1: note stem wins over everything else.
    if any(stem in cleaned for stem in _STEM_NOTE):
        return "edit_note"

    has_client_word = bool(_CLIENT_RE.search(cleaned))
    has_appt_word = bool(_APPT_RE.search(cleaned))

    # Rule 2: verb + «клиент» → delete_client (covers «удали клиента»,
    # «выкини клиента», «убери клиента»).
    if has_client_word and tokens & {"удали", "выкини", "убери"}:
        return "delete_client"

    # Rule 3: list-style verbs.
    if _has_verb(tokens, _VERBS_LIST):
        if has_client_word:
            return "list_clients"
        if has_appt_word:
            return "list_appointments"
        # «покажи Иру» — too ambiguous for keyword path. Let it fall through.

    # Rule 4: CREATE.
    if _has_verb(tokens, _VERBS_CREATE):
        # Edge case: «добавь Иру в клиенты» — there's no matching action
        # for «add client». Fall through to None.
        if has_client_word and tokens == {"добавь"} | tokens:
            # If the only create verb is «добавь» AND «клиент» appears,
            # it's not a valid create. Fall through.
            if "добавь" in tokens and not (tokens & (_VERBS_CREATE - {"добавь"})):
                return None
        return "create_appointment"

    # Rule 5: CANCEL (must come AFTER create since «удали» is in both
    # ambiguity sets — but cancel only fires here when neither client nor
    # note stem matched, so it's safe).
    if _has_verb(tokens, _VERBS_CANCEL):
        return "cancel_appointment"

    # Rule 6: RESCHEDULE.
    if _has_verb(tokens, _VERBS_RESCHEDULE):
        return "move_appointment"

    return None
