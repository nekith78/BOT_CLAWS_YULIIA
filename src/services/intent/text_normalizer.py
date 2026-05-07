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
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timezone
from datetime import time as _time
from typing import TYPE_CHECKING, Any, Literal

from src.bot.parsers import parse_time_from_text
from src.bot.relative_date import parse_relative_date

if TYPE_CHECKING:
    from src.storage.repositories.appointments import AppointmentRepository
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


# --- orchestration: extract, compute_missing, decide_next, build_canonical -


@dataclass(frozen=True)
class ClarifyOption:
    """One choice in a needs_clarification question. `value` is what the
    bot merges into `entities` when the user picks this option — for the
    appointment picker that's a dict carrying appointment_id + resolved
    name/date/time so the canonical builder has everything."""

    label: str
    value: dict[str, Any]


@dataclass(frozen=True)
class ClarifyQuestion:
    field: Literal[
        "appointment_ref",
        "note_text",
        "client",
        "date",
        "time",
        "new_date",
        "new_time",
    ]
    prompt: str
    editor: Literal[
        "calendar",
        "time_picker",
        "appointment_picker",
        "client_picker",
        "text_input",
    ]
    options: list[ClarifyOption] | None = None


@dataclass(frozen=True)
class NormalizationResult:
    kind: Literal["canonical_ready", "needs_clarification", "no_verb_detected"]
    canonical_text: str | None = None
    question: ClarifyQuestion | None = None


# Verb → required-fields list. `appointment_ref` is a virtual marker —
# decide_next resolves it against the DB before asking the user.
_VERB_REQUIRES: dict[str, tuple[str, ...]] = {
    "create_appointment": ("name", "date", "time"),
    "cancel_appointment": ("appointment_ref",),
    "move_appointment": ("appointment_ref", "new_date_or_time"),
    "edit_note": ("appointment_ref", "note_text"),
    "delete_client": ("client_id",),
    "list_appointments": (),
    "list_clients": (),
}


def compute_missing(verb: str, entities: dict[str, Any]) -> list[str]:
    """Return the ORDERED list of fields still needed for `verb` given
    what's in `entities`. Pure — no DB access."""
    required = _VERB_REQUIRES.get(verb, ())
    missing: list[str] = []
    for field in required:
        if field == "appointment_ref":
            if not entities.get("appointment_id"):
                missing.append("appointment_ref")
        elif field == "new_date_or_time":
            if not entities.get("new_date") and not entities.get("new_time"):
                missing.append("new_date_or_time")
        elif field == "client_id":
            if not entities.get("client_id"):
                missing.append("client_id")
        else:
            if not entities.get(field):
                missing.append(field)
    return missing


def build_canonical(verb: str, entities: dict[str, Any]) -> str:
    """Render a clean Russian sentence for LLM #2. Templates per spec §3.7."""
    name = entities.get("name") or ""
    date = entities.get("date") or ""
    time_ = entities.get("time") or ""
    note = entities.get("note") or ""
    note_text = entities.get("note_text") or ""
    insta = entities.get("instagram") or ""
    new_date = entities.get("new_date") or ""
    new_time = entities.get("new_time") or ""

    if verb == "create_appointment":
        parts = [f"запиши {name} на {date} в {time_}"]
        if note:
            parts.append(f"с заметкой {note}")
        if insta:
            parts.append(f"инстаграм {insta}")
        return " ".join(parts)
    if verb == "cancel_appointment":
        return f"отмени запись {name} {date} {time_}".rstrip()
    if verb == "move_appointment":
        target = []
        if new_date:
            target.append(new_date)
        if new_time:
            target.append(f"в {new_time}")
        target_str = " ".join(target)
        return f"перенеси запись {name} {date} {time_} на {target_str}"
    if verb == "edit_note":
        return f"добавь к записи {name} {date} {time_} заметку: {note_text}"
    if verb == "list_appointments":
        return f"покажи записи на {date}" if date else "покажи все записи"
    if verb == "list_clients":
        return "покажи всех клиентов"
    if verb == "delete_client":
        return f"удали клиента {name}"
    return ""


async def extract(
    text: str,
    today_local: _date,
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> dict[str, Any]:
    """Pass-1+pass-2 extraction on raw transcript. Returns `{}` if no
    verb was detected; otherwise a dict with at minimum `verb` plus any
    detected entities (name/client_id/date/time/note/instagram)."""
    if not text:
        return {}

    # Strip Instagram FIRST — IG markers are unambiguous, and note text
    # (which is free-form) might otherwise swallow «инстаграм X» as part
    # of the note tail.
    instagram, after_ig = extract_instagram(text)
    note, after_note = extract_note(after_ig)
    cleaned = after_note

    verb = detect_verb(cleaned)
    if verb is None:
        return {}

    iso_date = parse_relative_date(cleaned, today_local)
    hhmm = parse_time_from_text(cleaned)

    name_candidate = extract_name_candidate(cleaned, verb)
    name: str | None = None
    client_id: int | None = None
    if name_candidate:
        name, client_id = await resolve_client_candidate(name_candidate, repo)

    entities: dict[str, Any] = {"verb": verb}
    if name is not None:
        entities["name"] = name
    if client_id is not None:
        entities["client_id"] = client_id
    if iso_date:
        entities["date"] = iso_date
    if hhmm:
        entities["time"] = hhmm
    if note:
        entities["note"] = note
    if instagram:
        entities["instagram"] = instagram
    return entities


async def decide_next(
    entities: dict[str, Any],
    today_local: _date,
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> NormalizationResult:
    """Compute the next step: build canonical, ask a clarifying question,
    or report no-verb. Stateless — the bot persists `entities` between
    calls and merges the user's answer in before calling again."""
    verb = entities.get("verb")
    if not verb:
        return NormalizationResult(kind="no_verb_detected")

    # Try to resolve appointment_ref against the DB before asking.
    if (
        verb in {"cancel_appointment", "move_appointment", "edit_note"}
        and not entities.get("appointment_id")
    ):
        await _try_resolve_appointment_ref(
            entities, today_local, repo, appt_repo
        )

    missing = compute_missing(verb, entities)
    if not missing:
        return NormalizationResult(
            kind="canonical_ready",
            canonical_text=build_canonical(verb, entities),
        )

    # Ask for the FIRST missing entity (ordered by `_VERB_REQUIRES`).
    next_field = missing[0]
    question = await _build_question(next_field, entities, repo, appt_repo)
    return NormalizationResult(
        kind="needs_clarification",
        question=question,
    )


# --- internal helpers used by decide_next ---------------------------------


async def _try_resolve_appointment_ref(
    entities: dict[str, Any],
    today_local: _date,
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> None:
    """If exactly one DB appointment matches the (name, date) hints, fill
    appointment_id + name/date/time so the canonical builder has them."""
    name = entities.get("name")
    date_iso = entities.get("date")
    candidates = await _list_candidate_appointments(
        name=name, date_iso=date_iso, repo=repo, appt_repo=appt_repo
    )
    if len(candidates) == 1:
        a = candidates[0]
        client = await repo.get(a.client_id)
        local = a.starts_at.replace(tzinfo=timezone.utc)
        # We don't know `tz` here — appt_repo stores naive UTC. Keep it
        # simple: serialize as UTC date+time. Bot layer can render local
        # for display; LLM #2 only needs unique reference.
        entities["appointment_id"] = a.id
        if client and not entities.get("name"):
            entities["name"] = client.name
        entities["date"] = local.date().isoformat()
        entities["time"] = local.strftime("%H:%M")


async def _list_candidate_appointments(
    *,
    name: str | None,
    date_iso: str | None,
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> list[Any]:
    """Pick candidate appointments based on the entity hints we have."""
    # If a date is given, list that day's appointments and filter by name
    # afterward (DB list_for_date returns naive UTC — caller pretends UTC
    # is local, which is fine for the candidate-set heuristic).
    if date_iso:
        try:
            d = _date.fromisoformat(date_iso)
        except ValueError:
            return []
        # Use a UTC-naive zone to avoid a tz dependency at this layer.
        # The bot caller invokes decide_next with today_local in its own tz;
        # for selection we use the local-day window relative to that tz on
        # the UI layer, but for candidate-counting any conservative window
        # works. Read upcoming and filter by date to keep this stateless.
        all_upcoming = await appt_repo.list_upcoming(
            now=datetime.combine(d, _time(0, 0)), limit=200
        )
        on_date = [
            a for a in all_upcoming if a.starts_at.date() == d
        ]
        if name:
            client = await repo.find_by_name_ci(name)
            if client:
                on_date = [a for a in on_date if a.client_id == client.id]
        return on_date

    # No date — fall back to upcoming, possibly narrowed by name.
    upcoming = await appt_repo.list_upcoming(
        now=datetime.now(tz=timezone.utc).replace(tzinfo=None), limit=20
    )
    if name:
        client = await repo.find_by_name_ci(name)
        if client:
            upcoming = [a for a in upcoming if a.client_id == client.id]
    return upcoming


async def _build_question(
    next_field: str,
    entities: dict[str, Any],
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> ClarifyQuestion:
    """Translate a missing-field marker into a concrete user question."""
    if next_field == "appointment_ref":
        candidates = await _list_candidate_appointments(
            name=entities.get("name"),
            date_iso=entities.get("date"),
            repo=repo,
            appt_repo=appt_repo,
        )
        options = []
        for a in candidates:
            client = await repo.get(a.client_id)
            client_name = client.name if client else "?"
            label = f"{client_name} — {a.starts_at.strftime('%d.%m %H:%M')}"
            options.append(
                ClarifyOption(
                    label=label,
                    value={
                        "appointment_id": a.id,
                        "name": client_name,
                        "date": a.starts_at.date().isoformat(),
                        "time": a.starts_at.strftime("%H:%M"),
                    },
                )
            )
        return ClarifyQuestion(
            field="appointment_ref",
            prompt="К какой записи?",
            editor="appointment_picker",
            options=options,
        )

    if next_field == "note_text":
        return ClarifyQuestion(
            field="note_text",
            prompt="Напиши заметку:",
            editor="text_input",
        )

    if next_field == "name":
        clients = await repo.list_recent(limit=10)
        options = [
            ClarifyOption(
                label=c.name,
                value={"name": c.name, "client_id": c.id},
            )
            for c in clients
        ]
        return ClarifyQuestion(
            field="client",
            prompt="Какой клиент?",
            editor="client_picker",
            options=options,
        )

    if next_field == "client_id":
        clients = await repo.list_recent(limit=20)
        options = [
            ClarifyOption(
                label=c.name,
                value={"name": c.name, "client_id": c.id},
            )
            for c in clients
        ]
        return ClarifyQuestion(
            field="client",
            prompt="Какого клиента?",
            editor="client_picker",
            options=options,
        )

    if next_field == "date":
        return ClarifyQuestion(
            field="date", prompt="На какую дату?", editor="calendar"
        )
    if next_field == "time":
        return ClarifyQuestion(
            field="time", prompt="Во сколько?", editor="time_picker"
        )
    if next_field == "new_date_or_time":
        # Pick whichever is missing; both missing → ask for new_time first
        # (most common shape: «перенеси Иру на 16»).
        if not entities.get("new_time"):
            return ClarifyQuestion(
                field="new_time", prompt="На какое время?", editor="time_picker"
            )
        return ClarifyQuestion(
            field="new_date", prompt="На какую дату?", editor="calendar"
        )

    # Should not happen — defensive fallback.
    return ClarifyQuestion(
        field="note_text",
        prompt="Уточни команду:",
        editor="text_input",
    )

