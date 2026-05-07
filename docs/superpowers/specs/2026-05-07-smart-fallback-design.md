# Smart Fallback — Second Brain Text Normalizer (Design)

> Brainstorm date: 2026-05-07
> Builds on: Plan #4 (voice intake) and the per-field-edit / accuracy spec (`2026-05-07-voice-intake-edit-and-accuracy-design.md`).

## Goal

Two pain points in production voice/text intake:

1. **Ambiguous commands referencing existing records** — «отмени завтрашнюю запись», «добавь заметку на завтрашнюю запись». LLM either picks no tool or picks one without the required `client_name`, action returns FAIL, bot says «не понял». Should ask a clarifying question instead.
2. **Free-form commands the LLM misses entirely** — small free models (`gpt-oss-120b:free`) sometimes fail to choose a tool even on perfectly parseable text. Today the user is told «не понял команду» and has to retype.

Both are different surface symptoms of the same UX failure: bot refuses silently when it could have either executed or asked. Goal: never refuse silently — execute, ask, or at worst hint.

## Architecture context

Current voice/text pipeline (`bot/handlers/intake.py`):

```
voice/text → STT → LLM.parse_intent(...) → tool_name + args → action.plan() → CONFIRM | CLARIFY | EXECUTED | FAIL
```

When `tool_name is None`, `_help_text()` shows the «не понял» hint. When action returns FAIL with «client_name required», same outcome — generic hint. Both fail spots are the targets of this design.

## Decisions from brainstorm

1. **Two independent layers, both feeding the existing CONFIRM/CLARIFY mechanism.**
2. **Layer A — action tolerance**: actions handling existing records (cancel / reschedule / update_note / delete_client) accept partial args and return CLARIFY with options instead of FAIL.
3. **Layer B — second brain as text normalizer**, NOT a parallel intent parser. It rewrites the user's free-form text into a clean canonical Russian sentence that LLM #2 then turns into a tool call. Logic kept minimal in the bot.
4. **Three-stage pipeline cap**: LLM #1 → Second Brain (with optional clarifying questions) → LLM #2. If LLM #2 also returns no tool — «не понял». No more retries (no infinite loop).
5. **Coverage C** — all single-record actions: create_appointment, cancel, reschedule, update_note, list_appointments, list_clients, delete_client. Bulk and `count_*` actions stay LLM-only.
6. **Russian morphology — DB-first fuzzy match + simple ending dictionary**, no `pymorphy2`. Always show CONFIRM-card so the user can correct misparses.
7. **Multi-step clarification** for commands needing two answers (e.g., «добавь заметку на завтрашнюю запись» = pick record + write note text) — modeled as a question loop inside the second brain.
8. **Canonical text format A** — natural Russian with normalized values: `«запиши Ира на 2026-05-08 в 14:30 с заметкой френч»`. ISO date, HH:MM time, nominative names. LLM #2 gets a `is_canonical=True` hint in the system prompt.

---

## Section 1 — Pipeline overview

```
                voice/text transcript
                          │
                          ▼
              ┌───────────────────────┐
              │  LLM #1 (raw text)    │
              └───────────┬───────────┘
                          │
          tool_name? ─────┴────── tool_name=None
              │                        │
              ▼                        ▼
        action.plan()           ┌─────────────────────────┐
              │                 │  Second Brain analyser  │
        CONFIRM/CLARIFY/        │  • verb detection       │
        EXECUTED/FAIL           │  • entity extraction    │
                                │  • clarify-loop with    │
                                │    user (if needed)     │
                                │  • build canonical text │
                                └───────────┬─────────────┘
                                            │
                            verb detected? ─┴── no → «не понял»
                                            │ yes
                                            ▼
                              ┌───────────────────────────┐
                              │  LLM #2 (canonical text)  │
                              └────────────┬──────────────┘
                                           │
                          tool_name? ──────┴── None → «не понял»
                              │
                              ▼
                       action.plan() → CONFIRM/CLARIFY/...
```

Layer A (action tolerance) operates on **both** action.plan calls in this pipeline — the one after LLM #1 and the one after LLM #2. It is independent of the second brain.

---

## Section 2 — Layer A: action tolerance

Today some actions return FAIL when a required arg is missing. We turn the relevant FAILs into CLARIFY with a list of candidate records.

### 2.1 — Affected actions

| Action | Today's FAIL trigger | New CLARIFY behaviour |
|---|---|---|
| `cancel_appointment_by_client` | `client_name` empty | If `date` known → list appointments for that date. Else → list all upcoming (limit 10). |
| `reschedule_appointment_by_client` | `client_name` empty | List upcoming appointments, user picks one, then continue with the original `new_date`/`new_time`. |
| `update_note` | `client_name` empty | If `date` known → list that day's appointments. Else → list upcoming. After pick, action knows the appointment id. |
| `delete_client` | `client_id`/`client_name` empty | List of clients (most recent first, limit 20). |

### 2.2 — CLARIFY mechanism (already exists)

`ActionResponse(result=ActionResult.CLARIFY, clarify_options=[...])` — each option carries a `payload` patch and a `label`. Intake renders buttons. After tap, args merge with patch and `action.plan()` is re-called.

For Layer A we just populate `clarify_options` instead of returning FAIL when the missing arg is "the record itself". No infrastructure changes in `bot/handlers/intake.py`.

### 2.3 — Prompt update

The LLM system prompt gets a small clarification:

> Если ты не уверен, на какую именно запись ссылается команда, всё равно вызывай нужный инструмент с тем, что знаешь (например, только с датой). Инструмент сам уточнит у пользователя, какая запись имелась в виду.

This nudges the LLM to call tools with partial args instead of refusing.

---

## Section 3 — Layer B: second brain as text normalizer

### 3.1 — Module: `src/services/intent/text_normalizer.py`

Pure async function. No bot imports, no LLM imports — testable in isolation.

```python
@dataclass(frozen=True)
class NormalizationResult:
    kind: Literal["canonical_ready", "needs_clarification", "no_verb_detected"]
    canonical_text: str | None      # set if kind=canonical_ready
    question: ClarifyQuestion | None  # set if kind=needs_clarification

@dataclass(frozen=True)
class ClarifyQuestion:
    field: Literal["date", "time", "appointment_ref", "client", "note", "instagram"]
    prompt: str            # Russian text shown to user
    editor: Literal[
        "calendar", "time_picker", "appointment_picker",
        "client_picker", "text_input",
    ]
    options: list[ClarifyOption] | None  # for appointment_picker / client_picker

# Called ONCE on the initial transcript. Returns the verb plus everything
# we managed to extract from raw text — date, time, name candidate (already
# resolved against DB), note, instagram. No clarifying happens here.
async def extract(
    text: str,
    today_local: date,
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> dict[str, Any]:  # {"verb": ..., "date": ..., "time": ..., ...} or {} if no_verb
    ...

# Called repeatedly — first right after extract(), then once after each user
# clarification answer. Pure decision function: looks at what's already in
# `entities`, computes what's still missing, returns either canonical_ready or
# the next clarification to ask. Stateless from its own perspective; the bot
# stores the running `entities` dict in FSM and merges each user answer into
# it before re-calling.
async def decide_next(
    entities: dict[str, Any],
    today_local: date,
    repo: ClientRepository,
    appt_repo: AppointmentRepository,
) -> NormalizationResult:
    ...
```

The bot is responsible for FSM persistence; the normalizer is two pure functions over a plain dict.

### 3.2 — Verb detection (Section 4 vocabulary)

Scan `text.lower()` for verb markers, ordered by priority:

1. `"заметк"` stem present → `verb = update_note` (overrides everything else).
2. Verb in `{удали, выкини, убери}` AND `\bклиент(а|ов|у|ы)?\b` → `verb = delete_client`.
3. Verb in `{покажи, список, какие, кто}`:
    - `\bклиент(ов|а|ы)?\b` → `verb = list_clients`
    - `\bзапис(и|ей|ь|ью)\b` → `verb = list_appointments`
4. Verb in `{запиши, запишу, поставь, поставлю, создай, зафиксируй, добавь}` → `verb = create_appointment`.
5. Verb in `{отмени, удали, сними, убери}` → `verb = cancel_appointment`.
6. Verb in `{перенеси, передвинь, сдвинь, переставь, измени}` → `verb = reschedule_appointment`.
7. None matched → `kind = no_verb_detected`.

### 3.3 — Entity extraction

Reuse existing helpers; add three new ones in the normalizer module.

| Entity | Extractor | Module |
|---|---|---|
| `date` | `parse_relative_date(text, today)` | `src/bot/relative_date.py` (existing) |
| `time` | `parse_time_from_text(text)` | `src/bot/parsers.py` (existing) |
| `note` | `extract_note(text)` — find marker stem `заметк/пометк/припиш/допиш` → take everything after it | NEW (in normalizer) |
| `instagram` | `extract_instagram(text)` — `@\w+` regex or token after `инстаграм/инста/insta` | NEW |
| `client_name` | `extract_client_candidate(text)` + `resolve_client_candidate(...)` | NEW |

**Two-pass parsing:** first pass detects and **removes** the note segment (so it doesn't pollute name/time extraction); second pass works on the cleaned remainder.

### 3.4 — Russian name resolution

```python
async def resolve_client_candidate(
    candidate: str, repo: ClientRepository,
) -> tuple[str, int | None]:
    """Return (canonical_name, client_id_or_None)."""
    forms = denormalize_forms(candidate)  # returns 1–3 candidate nominatives
    for form in forms:
        client = await repo.find_by_name_ci(form)
        if client:
            return client.name, client.id
    # Fuzzy fallback — Levenshtein ≤ 1 against all client names.
    all_clients = await repo.list_all()
    for client in all_clients:
        for form in [candidate, *forms]:
            if levenshtein(form.lower(), client.name.lower()) <= 1:
                return client.name, client.id
    # Not found — return first denormalised form, no id.
    return forms[0], None
```

`denormalize_forms` — pure function, simple ending dictionary:

| Suffix in candidate | Try replacing with |
|---|---|
| `-у` | `-а` (Иру → Ира) |
| `-ю` | `-я` (Юлю → Юля) |
| `-ы` | `-а` (Иры → Ира) |
| `-и` | `-а`, `-я` (Маши → Маша; Юли → Юля) |
| `-е` | `-а`, `-я` (Ире → Ира; Маше → Маша) |
| (no suffix match) | candidate as-is |

Always include candidate as-is in the list (covers cases where user said the nominative outright). Levenshtein lives in `src/services/intent/text_normalizer.py` as a small private helper — no third-party dep.

### 3.5 — Verb-to-required-entities table

Used to compute `sb_missing` after each entity extraction pass.

| Verb | Required (must be present) | Optional (used if extracted) |
|---|---|---|
| `create_appointment` | `name`, `date`, `time` | `note`, `instagram` |
| `cancel_appointment` | `appointment_ref` (single record id; if name+date give exactly one match → resolved) | — |
| `reschedule_appointment` | `appointment_ref` + (`new_date` OR `new_time`) | the other of new_date/new_time |
| `update_note` | `appointment_ref` + `note_text` | — |
| `list_appointments` | (none) | `date_from`, `date_to` |
| `list_clients` | (none) | `query` |
| `delete_client` | `client_id` | — |

`appointment_ref` resolution:
- If `name` extracted AND resolves to exactly one upcoming appointment → ref is that appointment.
- If `name` AND `date` AND there's exactly one match → resolved.
- Otherwise — ref is missing, ask via `appointment_picker`.

### 3.6 — Clarify question loop

Bot side, after LLM #1 returns `tool_name=None`:

```
1. entities = await extract(transcript, today, repos)
2. if not entities.get("verb"):
       → replace status with «не понял» — END.
3. result = await decide_next(entities, today, repos)
4. branch on result.kind:
   - canonical_ready:
       → llm_response = await llm.parse_intent(result.canonical_text, ..., is_canonical=True)
       → if llm_response.tool_name: action.plan(...) — existing render path.
       → else: replace status with «не понял» — END.
   - needs_clarification:
       → save FSM: sb_verb=entities["verb"], sb_entities=entities, sb_msg_id=msg_id,
                    sb_field_being_asked=result.question.field
       → render result.question.editor on the same status message
       → set state: smart_brain_pick (for pickers) or smart_brain_text (for text_input)
       → END this dispatch; user's answer comes through one of the new handlers.
   - no_verb_detected:
       → replace status with «не понял» — END.
```

Question-answer handlers (new):

```
on_smart_brain_pick (state=smart_brain_pick, callback matches the editor's CD):
    1. fsm = state.get_data()
    2. entities = fsm["sb_entities"]
    3. entities[fsm["sb_field_being_asked"]] = decode_callback_to_value(...)
    4. state.update_data(sb_entities=entities)
    5. result = await decide_next(entities, today, repos)
    6. branch as in step 4 above (canonical / next question / unreachable no_verb).

on_smart_brain_text (state=smart_brain_text, F.text or F.voice):
    1. transcribe if voice; else use text
    2. fsm["sb_entities"][fsm["sb_field_being_asked"]] = value
    3. result = await decide_next(...) → branch as above.
```

Cancel handlers (new): `IntakePending.smart_brain_*` + IntakeCD `action="cancel_edit"` → `state.clear()` + edit message to «❌ Отменено».

Always leave a «❌ Отмена» button on widgets — taps it → `state.clear()` + edit message to «❌ Отменено».

### 3.7 — Building the canonical text

`build_canonical(entities) -> str`. Templates per verb, all natural Russian with ISO/HH:MM:

| Verb | Template |
|---|---|
| create_appointment | `«запиши {name} на {date} в {time}»` (+ `« с заметкой {note}»` if present, + `« инстаграм {instagram}»` if present) |
| cancel_appointment | `«отмени запись {name} на {date} в {time}»` (always full ref since we resolved it) |
| reschedule_appointment | `«перенеси запись {name} {date} {time} на {new_date} в {new_time}»` |
| update_note | `«добавь к записи {name} {date} {time} заметку: {note_text}»` |
| list_appointments | `«покажи записи на {date}»` (if date given) or `«покажи все записи»` |
| list_clients | `«покажи всех клиентов»` |
| delete_client | `«удали клиента {name}»` |

LLM #2 with system prompt hint `is_canonical=True` reliably maps these to tool calls.

---

## Section 4 — Verb vocabulary (locked from brainstorm)

Sets used by the verb-detection rules in §3.2:

```python
VERBS_CREATE      = {"запиши", "запишу", "поставь", "поставлю", "создай", "зафиксируй", "добавь"}
VERBS_CANCEL      = {"отмени", "удали", "сними", "убери"}
VERBS_RESCHEDULE  = {"перенеси", "передвинь", "сдвинь", "переставь", "измени"}
VERBS_LIST        = {"покажи", "список", "какие", "кто"}
NOUN_APPOINTMENT  = ("запис",)   # stem: запись/записей/записи/записью
NOUN_CLIENT       = ("клиент",)  # stem with strict word-boundary, NOT «клиентский»
STEM_NOTE         = ("заметк", "пометк", "припиш", "допиш")
```

Word-boundary regex for `клиент`: `\bклиент(а|ов|у|ы)?\b` — explicitly does NOT match «клиентск-».

Edge cases (locked):
- `«удали Иру»` → no `клиент`, no `заметк` → `cancel_appointment`. Action's CLARIFY handles single-vs-many.
- `«добавь Иру в клиенты»` → has `клиент`, has `добавь` — no matching action exists. Returns `no_verb_detected`. Acceptable.
- `«покажи Иру»` → no `запис`/`клиент` → `no_verb_detected`. Too ambiguous for keyword path.

---

## Section 5 — FSM states and storage

### 5.1 — New states

```python
class IntakePending(StatesGroup):
    # existing:
    confirming = State()
    clarifying = State()
    choosing_edit_field = State()
    editing_field_picker = State()
    editing_field_text = State()
    # NEW:
    smart_brain_pick = State()  # awaiting button-pick on a normalizer question
    smart_brain_text = State()  # awaiting free text for a normalizer question
```

### 5.2 — FSM data keys (prefixed `sb_`)

| Key | Type | Purpose |
|---|---|---|
| `sb_verb` | str | detected verb (one of the seven supported) |
| `sb_entities` | dict | `{date, time, name, client_id, appointment_id, note, instagram, new_date, new_time}` |
| `sb_msg_id` | int | bot status message id, edited in place |
| `sb_field_being_asked` | str | current question's field, for routing the answer |

### 5.3 — Lifecycle

`_dispatch` (existing) is extended — pseudocode in §3.6.

Voice/text intake routing (`on_voice`, `on_text`) gets `~StateFilter(IntakePending.smart_brain_text)` added so a free-text answer to the normalizer's question doesn't accidentally re-enter the LLM intake (same pattern already used for `editing_field_text`).

`_try_wizard_consume` (in `bot/handlers/intake.py`) is also extended to recognise `smart_brain_text` state — though in practice the dedicated state-filtered handler catches it first.

---

## Section 6 — System prompt for LLM #2

`build_system_prompt(...)` gains an `is_canonical: bool = False` argument. When True, append:

> Текст в этом сообщении уже нормализован: даты в формате `YYYY-MM-DD`, время в формате `HH:MM`, имена в именительном падеже. Доверяй этим значениям и вызывай соответствующий tool без дополнительных интерпретаций.

This block is appended after the existing rules and few-shot examples.

The existing system prompt also gets the Layer A nudge described in §2.3.

---

## Section 7 — What we explicitly do NOT do

- **Bulk commands** («отмени всё на завтра», «удали всех клиентов с инстаграмом X») are not handled by the normalizer. If LLM #1 misses them, user gets «не понял».
- **`count_*` and `show_history`** stay LLM-only.
- **No third LLM retry** — strict 2-LLM-calls-per-input cap.
- **No `pymorphy2`** — only the ending dictionary in §3.4. Trade-off: misses unusual case forms; covered by always showing CONFIRM-card so user can correct.
- **No second-brain-first path** (saving LLM quota) — LLM is always called first for natural-language understanding. Quota saving is a deferred optimisation.
- **No name extraction from purely uppercase-cased tokens** — STT lowercases, so we go positional (between verb and preposition) instead.

---

## Section 8 — Test strategy

### 8.1 — Unit tests (no bot, no LLM)

`tests/services/intent/test_text_normalizer.py`:

- Verb detection: 20+ phrases, each mapped to expected verb (or `no_verb`).
- Entity extraction: known-good phrases for date, time, note, instagram, name candidate.
- Name denormalization: «Иру/Машу/Юлю/Иры/Маши/Ире» → expected nominative.
- Levenshtein fuzzy: «Ера → Ира» (DB has «Ира»), «Машь → Маша».
- Note text extraction: «заметка: X» / «припиши Y что Z» / «с заметкой Q».
- Instagram extraction: `@nickname`, `инстаграм @x`, `insta x`.
- Two-pass: «запиши Иру на завтра 14 заметка френч» → entities = {name=Ира, date=tomorrow_iso, time=14:00, note=френч}.
- Required-fields computation per verb.
- Canonical text builders per verb.

### 8.2 — Layer A action tests

`tests/services/intent/actions/test_cancel_partial.py`, `test_reschedule_partial.py`, `test_update_note_partial.py`, `test_delete_client_partial.py`:

- Action with empty `client_name` and given `date` → CLARIFY with appointments-on-date.
- Action with empty `client_name` and no date → CLARIFY with upcoming.
- Action with `client_name` matching multiple appointments → CLARIFY with that client's appointments.

### 8.3 — Bot-layer tests

`tests/bot/test_smart_brain_flow.py`:

- LLM #1 returns None → normalizer returns canonical → LLM #2 stub returns tool → action runs.
- LLM #1 returns None → normalizer needs_clarification (appointment pick) → user picks → normalizer canonical → LLM #2 → action runs.
- LLM #1 returns None → normalizer needs_clarification (note text) → user types → normalizer canonical → LLM #2 → action runs.
- LLM #1 returns None → normalizer no_verb_detected → «не понял».
- LLM #1 returns None → normalizer canonical → LLM #2 returns None → «не понял» (no third retry).
- Cancel during smart_brain_pick / smart_brain_text → state cleared, message replaced with «❌ Отменено».

LLM stubs use a fake `IntentParser` that returns canned responses based on input text.

### 8.4 — Existing test suite

All 366 currently passing tests must keep passing. New states must not interfere with the existing CONFIRM/CLARIFY/edit flows.

---

## Section 9 — Out of scope / future work

- Pre-LLM keyword path for quota saving (run normalizer FIRST when very confident → skip LLM #1).
- Bulk-command parsing in normalizer.
- `pymorphy2` if the ending dictionary proves insufficient.
- Multi-turn conversation memory beyond the existing 3-turn deque (e.g., «и ещё на 16:00» follow-up to a fresh confirm).

---

## Implementation phases (high-level — detailed plan in writing-plans skill)

1. **Layer A** — make four actions tolerant. Smallest, most isolated. Ship behind feature flag if cautious.
2. **Normalizer module** — pure function, no bot integration. Full unit-test coverage.
3. **Bot wiring** — new FSM states, dispatch branch, question/answer handlers.
4. **System prompt updates** — `is_canonical` flag + Layer A nudge.
5. **Integration tests** — full LLM #1 → normalizer → LLM #2 paths with stubbed LLM.
6. **Manual smoke test** — Russian voice phrases on a live bot.

Each phase is independently mergeable (Layer A doesn't depend on the normalizer; the normalizer module is testable without bot wiring).
