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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.repositories.clients import ClientRepository

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


# --- entity extractors ----------------------------------------------------
#
# Each extractor returns `(value, cleaned_remainder)`. Returning the
# remainder enables a two-pass design: the first pass strips note/instagram
# segments so they don't pollute name/time/date detection on the second pass.


# Two kinds of note markers:
#  - keyword nouns that introduce the note text directly: «заметка», «заметку»,
#    «с заметкой», «пометка», «пометку».
#  - intro VERBS — «припиши», «допиши» — when they start the phrase, they get
#    stripped, and an inner marker («что» or «:») separates the addressee from
#    the note text. So «припиши Маше что ноготь треснул» splits into
#    remainder=«Маше», note=«ноготь треснул».
_NOTE_KEYWORD_MARKERS = (
    "с заметкой",
    "с пометкой",
    "заметка",
    "заметку",
    "пометка",
    "пометку",
)
_NOTE_INTRO_VERBS = ("припиши", "допиши")
_NOTE_GLUE_RE = re.compile(r"^\s*(?:что|:|—|-)\s*", re.IGNORECASE)
_NOTE_INNER_MARKER_RE = re.compile(r"\bчто\b|:", re.IGNORECASE)


def extract_note(text: str) -> tuple[str | None, str]:
    """Return `(note_or_None, text_with_note_segment_removed)`.

    Two modes:
    1. Phrase starts with «припиши»/«допиши» → strip the verb, find inner
       «что»/«:» marker, split there.
    2. Keyword marker found anywhere → split at the marker.
    """
    if not text:
        return None, text

    stripped = text.strip()
    lowered = stripped.lower()

    # Mode 1: note-intro verb at the start.
    for verb in _NOTE_INTRO_VERBS:
        if lowered.startswith(verb) and (
            len(stripped) == len(verb) or stripped[len(verb)].isspace()
        ):
            after_verb = stripped[len(verb) :].lstrip()
            m = _NOTE_INNER_MARKER_RE.search(after_verb)
            if m:
                before = after_verb[: m.start()].rstrip()
                after = after_verb[m.end() :].strip()
                if not after:
                    return None, text
                return after, before
            # No inner marker — can't tell where the note starts. Bail.
            return None, text

    # Mode 2: keyword markers.
    best_pos: int | None = None
    best_marker_len = 0
    for marker in _NOTE_KEYWORD_MARKERS:
        idx = lowered.find(marker)
        if idx >= 0 and (best_pos is None or idx < best_pos):
            best_pos = idx
            best_marker_len = len(marker)

    if best_pos is None:
        return None, text

    before = stripped[:best_pos].rstrip()
    after = stripped[best_pos + best_marker_len :]
    after = _NOTE_GLUE_RE.sub("", after).strip()
    if not after:
        # «заметку» as a bare word with nothing after — no note.
        return None, text
    return after, before


# `@handle` first; «инстаграм/инста/insta <handle>» second.
_AT_HANDLE_RE = re.compile(r"@([A-Za-z0-9_.]+)")
_IG_MARKER_RE = re.compile(
    r"\b(?:инстаграм|инста|insta(?:gram)?)\s+@?([A-Za-z0-9_.]+)",
    re.IGNORECASE,
)


def extract_instagram(text: str) -> tuple[str | None, str]:
    """Return `(@handle_or_None, text_with_segment_removed)`.

    Tries the «инстаграм/инста/insta <handle>» pattern first so the marker
    word is also stripped from the remainder. Falls back to a bare `@handle`
    anywhere in the text."""
    if not text:
        return None, text

    m = _IG_MARKER_RE.search(text)
    if m:
        handle = "@" + m.group(1)
        cleaned = (text[: m.start()] + text[m.end() :]).strip()
        return handle, cleaned

    m2 = _AT_HANDLE_RE.search(text)
    if m2:
        handle = "@" + m2.group(1)
        cleaned = (text[: m2.start()] + text[m2.end() :]).strip()
        return handle, cleaned

    return None, text


# --- name extraction ------------------------------------------------------
#
# Names sit positionally between the verb and the next anchor: a Russian
# preposition, a date/time token, or end-of-string. We strip out filler
# stop-words like «запись/клиент» that may sit between the verb and the
# actual name.

_NAME_STOPWORDS = {
    # «запись»/«клиент» as object-nouns inside the command.
    "запись",
    "записи",
    "записей",
    "записью",
    "клиент",
    "клиента",
    "клиентов",
    "клиенту",
    "клиенты",
    # Date adjectives — never names. Covers «отмени завтрашнюю» and ilk.
    "сегодняшнюю",
    "сегодняшний",
    "сегодняшнее",
    "сегодняшняя",
    "завтрашнюю",
    "завтрашний",
    "завтрашнее",
    "завтрашняя",
    "вчерашнюю",
    "вчерашний",
    "вчерашнее",
    "вчерашняя",
    # Bare relative-date words that could leak in.
    "сегодня",
    "завтра",
    "послезавтра",
    "вчера",
    # Days of the week — can come after «отмени Иру в понедельник» but
    # we stop on «в» preposition first, so listing them is defensive.
    "понедельник",
    "вторник",
    "среду",
    "среда",
    "четверг",
    "пятницу",
    "пятница",
    "субботу",
    "суббота",
    "воскресенье",
}
# Russian prepositions that anchor the END of the name slot.
_NAME_END_PREPS = {"на", "к", "ко", "с", "со", "у", "во", "в", "о", "об"}
# A token is "date/time-like" if it contains a digit anywhere — covers
# «14», «14:30», «8.05», «2026-05-08».
_DIGIT_RE = re.compile(r"\d")
# Tokeniser preserving ordering of words; punctuation is dropped.
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]+|\d[\d:.\-/]*", re.UNICODE)


def extract_name_candidate(text: str, verb: str) -> str | None:
    """Return the raw (possibly inflected) name candidate, or None.

    `verb` is the output of `detect_verb` — for list verbs we don't try
    to extract a name. The candidate is tokens between the verb and the
    first anchor (preposition, date/time-like token, end-of-string),
    minus stop-words like «запись»."""
    if not text or verb in {"list_appointments", "list_clients"}:
        return None

    tokens = _WORD_RE.findall(text)
    if not tokens:
        return None
    lowered = [t.lower() for t in tokens]

    # Find the verb token. Any token in any verb set counts as the anchor.
    verb_idx = -1
    for i, tok in enumerate(lowered):
        if (
            tok in _VERBS_CREATE
            or tok in _VERBS_CANCEL
            or tok in _VERBS_RESCHEDULE
            or tok in _VERBS_LIST
            or tok in {"припиши", "допиши"}
        ):
            verb_idx = i
            break
    if verb_idx < 0:
        return None

    # Walk forward from verb+1 collecting Cyrillic word tokens until we
    # hit an anchor.
    collected: list[str] = []
    for i in range(verb_idx + 1, len(tokens)):
        tok = tokens[i]
        low = lowered[i]
        if low in _NAME_END_PREPS:
            break
        if _DIGIT_RE.search(tok):
            break
        if low in _NAME_STOPWORDS:
            # Skip stop-words; keep walking — name may follow.
            if collected:
                break
            continue
        # Skip unrelated note marker stems if they sneak in (defensive).
        if any(stem in low for stem in _STEM_NOTE):
            break
        collected.append(tok)

    if not collected:
        return None
    # Trailing punctuation on the last token (e.g., «Иру:») is unlikely
    # because our regex already excludes punctuation, but be safe.
    return " ".join(collected).strip(" :,.")


# --- name resolution: morphology + DB fuzzy match -------------------------
#
# Tiny suffix-replacement table, no `pymorphy2` dep. Covers the common
# female-name accusative / genitive / dative forms that show up in voice
# commands («Иру/Машу/Юлю/Ире/Ирe/Маши/Юли»).

_DENORMALIZE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # accusative -у → -а  (Иру → Ира, Машу → Маша, Аню → Аня)
    ("у", ("а",)),
    # accusative -ю → -я  (Юлю → Юля, Катю → Катя)
    ("ю", ("я",)),
    # genitive  -ы → -а  (Иры → Ира)
    ("ы", ("а",)),
    # genitive/prepositional -и → -а / -я  (Маши → Маша, Юли → Юля)
    ("и", ("а", "я")),
    # dative/prepositional -е → -а / -я    (Ире → Ира, Маше → Маша)
    ("е", ("а", "я")),
)


def denormalize_forms(candidate: str) -> list[str]:
    """Return possible nominative forms for `candidate`. Always includes
    the candidate as-is at the front (user might already speak in nominative)."""
    candidate = candidate.strip()
    if not candidate:
        return []
    seen = {candidate}
    forms = [candidate]
    last_char = candidate[-1].lower()
    for suffix, replacements in _DENORMALIZE_RULES:
        if last_char == suffix:
            stem = candidate[:-1]
            for rep in replacements:
                form = stem + rep
                if form not in seen:
                    seen.add(form)
                    forms.append(form)
    return forms


def levenshtein(a: str, b: str) -> int:
    """Edit distance between `a` and `b`. Standard DP, two-row variant —
    fast enough for the small client lists in this bot (<100 entries)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,    # insert
                prev[j] + 1,        # delete
                prev[j - 1] + cost,  # substitute
            )
        prev = curr
    return prev[-1]


async def resolve_client_candidate(
    candidate: str,
    repo: ClientRepository,
) -> tuple[str, int | None]:
    """Try to map a possibly-inflected name to a real client.

    Strategy:
        1. Generate denormalised forms.
        2. Try EXACT case-insensitive match against the DB for each form.
        3. Fall back to Levenshtein ≤ 1 over all clients.
        4. Otherwise return the first denormalised form (good for create-new).

    Returns `(name, client_id_or_None)` — name is canonical when matched."""
    forms = denormalize_forms(candidate)
    if not forms:
        return candidate, None

    for form in forms:
        client = await repo.find_by_name_ci(form)
        if client is not None:
            return client.name, client.id

    # Fuzzy fallback. Compare each form against every client name.
    all_clients = await repo.list_all()
    for client in all_clients:
        target = client.name.lower()
        for form in forms:
            if levenshtein(form.lower(), target) <= 1:
                return client.name, client.id

    # No match — pick the most likely nominative as the new-client name.
    # Index 0 is the candidate as-is; index 1+ are denormalised. Prefer 1
    # if denormalisation produced anything, else fall back to 0.
    return (forms[1] if len(forms) > 1 else forms[0]), None

