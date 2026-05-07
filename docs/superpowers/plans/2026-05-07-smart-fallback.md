# Smart Fallback — Second Brain Text Normalizer (Plan #6)

> **For agentic workers:** TDD per task — failing test → impl → ruff/mypy clean → commit. Pure-function modules first; bot wiring last. Stay on branch `plan/smart-fallback` (forked from `plan/voice-intake-edit`).

> Spec: [docs/superpowers/specs/2026-05-07-smart-fallback-design.md](../specs/2026-05-07-smart-fallback-design.md)

**Goal:** stop the bot from saying «не понял команду» when it could either ask a clarifying question or normalize the user's free-form text into a clean Russian sentence the LLM can definitely tool-call on.

Two independent layers, both feeding the existing CONFIRM/CLARIFY render path:

1. **Layer A — action tolerance.** Four single-record actions (`cancel_appointment_by_client`, `reschedule_appointment_by_client`, `update_note`, `delete_client`) accept partial args and return CLARIFY with a list of candidate records instead of FAIL.
2. **Layer B — second brain text normalizer.** When LLM #1 returns `tool_name=None`, a pure-function normalizer extracts verb + entities from the raw text, asks clarifying questions if anything required is missing, then constructs a canonical Russian sentence (`«запиши Ира на 2026-05-08 в 14:30»`) and feeds it to LLM #2. Hard cap of two LLM calls per user input — no infinite retry.

**Architecture context:** Plan #4 (voice intake) merged. Plan #5 (per-field edit + few-shot prompt) merged. Action registry, OpenRouter LLM client, intake handler, FSM `IntakePending` group, confirm/clarify/edit-flow plumbing — all in place.

**Tech stack additions:** none. Reuses `calendar_kb`, `time_picker_kb`, `client_picker_kb`, the existing `IntakeCD` callback, and the `editing_field_text` text-input pattern.

**Prerequisites:**
- master + `plan/voice-intake-edit` ahead with the full Plan #5 + universal wizard-consumer commit (`8e825cc`).
- All 366 tests green, ruff/mypy clean.

**Decisions (from brainstorm 2026-05-07):**
1. Two-layer architecture, both targeting the existing CONFIRM/CLARIFY render path.
2. Three-stage cap: LLM #1 → Second Brain → LLM #2 → «не понял».
3. Coverage C — every single-record action (no bulk, no `count_*`).
4. Russian morphology via ending dictionary + DB fuzzy match (Levenshtein ≤ 1). No `pymorphy2`.
5. Multi-step clarification via a question loop in the normalizer (FSM state per round).
6. Canonical text format A — natural Russian, ISO dates, HH:MM times, nominative names.
7. New FSM states: `IntakePending.smart_brain_pick` and `IntakePending.smart_brain_text`.

---

## File Structure

| Путь | Назначение |
|---|---|
| `src/services/intent/text_normalizer.py` | _New_ — `extract`, `decide_next`, `build_canonical`, `denormalize_forms`, `levenshtein`, vocab sets |
| `src/services/intent/actions/cancel_appointment_by_client.py` | _Modify_ — Layer A: CLARIFY when `client_name` empty |
| `src/services/intent/actions/reschedule_appointment_by_client.py` | _Modify_ — Layer A |
| `src/services/intent/actions/update_note.py` | _Modify_ — Layer A |
| `src/services/intent/actions/delete_client.py` | _Modify_ — Layer A |
| `src/services/intent/prompt.py` | _Modify_ — `is_canonical` flag + Layer A nudge in main prompt |
| `src/storage/repositories/clients.py` | _Modify_ — add `find_by_name_ci`, `list_all` (if not present) |
| `src/storage/repositories/appointments.py` | _Modify_ — add `list_for_date`, `list_upcoming` (if not present) |
| `src/bot/states.py` | _Modify_ — add `smart_brain_pick`, `smart_brain_text` |
| `src/bot/callback_data.py` | _Modify_ — `IntakeCD.action` literal gets `"sb_pick"`, payload field already covers `index` |
| `src/bot/keyboards/appointment_picker.py` | _New_ — list-of-appointments keyboard for «какую запись?» |
| `src/bot/handlers/intake.py` | _Modify_ — extend `_dispatch` with normalizer branch; new handlers `on_smart_brain_pick`, `on_smart_brain_text`, `on_smart_brain_voice`, `on_smart_brain_cancel`; add `~StateFilter(IntakePending.smart_brain_text)` to `on_voice`/`on_text`; extend `_try_wizard_consume` |
| `tests/services/intent/test_text_normalizer.py` | _New_ — unit tests for verb detection, entities, canonical builder, name resolution |
| `tests/services/intent/actions/test_cancel_partial.py` etc. | _New_ — Layer A tests per action |
| `tests/bot/test_smart_brain_flow.py` | _New_ — bot-layer integration with stubbed LLM |

---

## Tasks

### Task 1: Branch + FSM/callback foundation

- [ ] **Step 1.1** Create branch `plan/smart-fallback` from `plan/voice-intake-edit`.
- [ ] **Step 1.2** Failing test: `IntakePending.smart_brain_pick` and `IntakePending.smart_brain_text` exist and are unique state names.
- [ ] **Step 1.3** Implement: add the two states to `src/bot/states.py`.
- [ ] **Step 1.4** Failing test: `IntakeCD(action="sb_pick", tag="abc", index=2).pack()` round-trips through `unpack`.
- [ ] **Step 1.5** Extend `IntakeCD.action` literal in `src/bot/callback_data.py` with `"sb_pick"`. (`index` field already exists for clarify; `field` is unused here.)
- [ ] **Step 1.6** ruff/mypy/pytest. Commit: `feat(bot): smart-brain FSM states + sb_pick callback`.

### Task 2: Repo helpers needed by Layer A and the normalizer

- [ ] **Step 2.1** Survey: which of these already exist? `ClientRepository.find_by_name_ci`, `list_all` (or paginated). `AppointmentRepository.list_for_date`, `list_upcoming(limit)`. Read the modules.
- [ ] **Step 2.2** Failing test for any missing helper. `find_by_name_ci("ира")` finds a client whose name is "Ира".
- [ ] **Step 2.3** Failing test: `list_upcoming(limit=10)` returns appointments in the future, sorted ascending by datetime.
- [ ] **Step 2.4** Failing test: `list_for_date(iso_date)` returns appointments on that local date in TZ-aware slot ordering.
- [ ] **Step 2.5** Implement the missing helpers minimally. Existing tests (366) must keep passing.
- [ ] **Step 2.6** ruff/mypy/pytest. Commit: `feat(storage): repo helpers for smart-fallback (find_by_name_ci, list_for_date, list_upcoming)`.

### Task 3: Layer A — `cancel_appointment_by_client` tolerance

- [ ] **Step 3.1** Failing test: action with `client_name=""` and `date="2026-05-08"` and three appointments on that date → result is CLARIFY with three options, each `payload` carries `appointment_id` and `client_name`, labels show «Имя — HH:MM».
- [ ] **Step 3.2** Failing test: action with `client_name=""` and no date → CLARIFY with up to 10 upcoming appointments (sorted ascending).
- [ ] **Step 3.3** Failing test: action with `client_name=""` and date but zero appointments on that date → FAIL with «На <date> нет записей.» (regression check — empty case stays a FAIL).
- [ ] **Step 3.4** Failing test: action with `client_name="Ира"` matching a client with multiple upcoming appointments → CLARIFY with that client's appointments only.
- [ ] **Step 3.5** Implement the new branches in `cancel_appointment_by_client.py`. Reuse `clarify_options` mechanism.
- [ ] **Step 3.6** ruff/mypy/pytest. Commit: `feat(intent): cancel_appointment tolerates partial args`.

### Task 4: Layer A — `reschedule_appointment_by_client`, `update_note`, `delete_client`

- [ ] **Step 4.1** `reschedule_appointment_by_client`: failing test for `client_name=""` with `new_date`/`new_time` → CLARIFY with upcoming appointments. After pick, replan with `appointment_id` carries the move forward.
- [ ] **Step 4.2** Implement.
- [ ] **Step 4.3** `update_note`: failing test for `client_name=""` with `date` → CLARIFY with that day's appointments. After pick, replan with `appointment_id`. (Empty `note_text` stays a separate FAIL/CLARIFY — handled later in the normalizer's loop, NOT here.)
- [ ] **Step 4.4** Implement.
- [ ] **Step 4.5** `delete_client`: failing test for empty `client_id`/`client_name` → CLARIFY with up to 20 most recent clients.
- [ ] **Step 4.6** Implement.
- [ ] **Step 4.7** Sanity: existing CONFIRM paths unchanged for these actions when args are full.
- [ ] **Step 4.8** ruff/mypy/pytest. Commit: `feat(intent): reschedule + update_note + delete_client tolerate partial args`.

### Task 5: Normalizer — vocab + verb detection (pure functions)

- [ ] **Step 5.1** Failing tests in `tests/services/intent/test_text_normalizer.py`. Cases:
  - `«запиши Иру на завтра в 14»` → verb = `create_appointment`
  - `«отмени завтрашнюю»` → verb = `cancel_appointment`
  - `«удали Иру»` → verb = `cancel_appointment` (no «клиент» word)
  - `«удали клиента Машу»` → verb = `delete_client`
  - `«перенеси Иру на 16»` → verb = `reschedule_appointment`
  - `«добавь заметку Маше»` → verb = `update_note`
  - `«покажи записи на завтра»` → verb = `list_appointments`
  - `«покажи клиентов»` → verb = `list_clients`
  - `«добавь Иру в клиенты»` → no verb (acceptable miss)
  - `«покажи Иру»` → no verb (too ambiguous)
  - `«привет, как дела»` → no verb
- [ ] **Step 5.2** Implement `detect_verb(text: str) -> str | None` in `src/services/intent/text_normalizer.py` with the vocab sets and priority rules from the spec §3.2 / §4.
- [ ] **Step 5.3** ruff/mypy/pytest. Commit: `feat(intent): text-normalizer verb detection`.

### Task 6: Normalizer — entity extractors

- [ ] **Step 6.1** Failing tests for `extract_note(text) -> tuple[str | None, str]` (returns `(note_text_or_None, cleaned_text_without_note)`):
  - `«запиши Иру на завтра 14 заметка френч»` → `("френч", «запиши Иру на завтра 14»)`
  - `«припиши Маше что ноготь треснул»` → `("ноготь треснул", «припиши Маше»)`
  - `«отмени завтрашнюю»` → `(None, «отмени завтрашнюю»)`
- [ ] **Step 6.2** Implement `extract_note`. Marker stems: `заметк`, `пометк`, `припиш`, `допиш` + the optional `что/:` after the stem.
- [ ] **Step 6.3** Failing tests for `extract_instagram(text) -> tuple[str | None, str]`:
  - `«@ira_nails»` → `("@ira_nails", "")`
  - `«инстаграм ira_nails»` → `("@ira_nails", "")`
  - `«запиши Иру»` → `(None, «запиши Иру»)`
- [ ] **Step 6.4** Implement `extract_instagram`.
- [ ] **Step 6.5** Failing tests for `extract_name_candidate(text, verb) -> str | None`. Positional extraction between verb and the next preposition/marker:
  - `«запиши Иру на завтра в 14»` → `"Иру"`
  - `«отмени запись Маши на завтра»` → `"Маши"` (skip stop-word «запись»)
  - `«перенеси Анну Сергеевну на 16»` → `"Анну Сергеевну"`
  - `«покажи записи на завтра»` → `None` (verb=list, name not expected)
- [ ] **Step 6.6** Implement `extract_name_candidate`. Stop-words: `запись`, `записи`, `клиент`, `клиента`. Anchors: prepositions `на|к|с|у|во|в`, dates, times, end-of-string.
- [ ] **Step 6.7** ruff/mypy/pytest. Commit: `feat(intent): text-normalizer entity extractors (note, instagram, name candidate)`.

### Task 7: Normalizer — name resolution (denormalize + Levenshtein + DB lookup)

- [ ] **Step 7.1** Failing tests for `denormalize_forms(candidate: str) -> list[str]`:
  - `"Иру"` → contains `"Ира"`
  - `"Машу"` → contains `"Маша"`
  - `"Юлю"` → contains `"Юля"`
  - `"Иры"` → contains `"Ира"`
  - `"Маши"` → contains `"Маша"`
  - `"Юли"` → contains `"Юля"`
  - `"Ире"` → contains `"Ира"`
  - `"Ира"` → contains `"Ира"` (identity)
- [ ] **Step 7.2** Implement `denormalize_forms` with the suffix table from spec §3.4. Always include the candidate as-is.
- [ ] **Step 7.3** Failing tests for `levenshtein(a: str, b: str) -> int`: identity = 0, single insertion/deletion/substitution = 1, two-edit cases = 2.
- [ ] **Step 7.4** Implement `levenshtein` (small private helper, dynamic programming).
- [ ] **Step 7.5** Failing tests for `resolve_client_candidate(candidate, repo) -> tuple[str, int | None]` (async; uses an in-memory repo fixture):
  - DB has `Ира` → `resolve("Иру", repo)` → `("Ира", <id>)`.
  - DB has `Маша` → `resolve("Машу", repo)` → `("Маша", <id>)`.
  - DB has `Ира` → `resolve("Ера", repo)` → `("Ира", <id>)` via Levenshtein ≤ 1.
  - DB empty → `resolve("Иру", repo)` → `("Ира", None)` (denormalised first form, no id).
  - DB has `Аня` and `Юра` → `resolve("Юлю", repo)` → `("Юля", None)` (no fuzzy match within 1 edit).
- [ ] **Step 7.6** Implement `resolve_client_candidate`.
- [ ] **Step 7.7** ruff/mypy/pytest. Commit: `feat(intent): name resolution — denormalize + DB fuzzy match`.

### Task 8: Normalizer — `extract`, `decide_next`, `build_canonical`

- [ ] **Step 8.1** Failing test for `extract(text, today, repos)`. Two-pass:
  - `«запиши Иру на завтра 14:30 заметка френч»` (DB has «Ира») →
    `{"verb": "create_appointment", "name": "Ира", "client_id": <id>, "date": "<tomorrow>", "time": "14:30", "note": "френч", "instagram": None, "raw_candidate": "Иру"}`
  - `«привет»` → `{}` (no verb)
- [ ] **Step 8.2** Implement `extract`. First pass strips note/instagram. Second pass detects verb, date, time, name candidate. Resolves name via repo.
- [ ] **Step 8.3** Failing test for `compute_missing(verb, entities) -> list[str]`. Pairs from spec §3.5:
  - `create_appointment, {name, date, time}` → `[]`
  - `create_appointment, {name, date}` → `["time"]`
  - `update_note, {appointment_id}` → `["note_text"]`
  - `cancel_appointment, {name, date} with multiple matches` → `["appointment_ref"]`
  - `cancel_appointment, {appointment_id}` → `[]`
- [ ] **Step 8.4** Implement `compute_missing`. For verbs that take `appointment_ref`, resolve the ref by looking up matching appointments — if exactly one match, fill `appointment_id` and skip; otherwise mark `appointment_ref` as missing.
- [ ] **Step 8.5** Failing test for `build_canonical(verb, entities) -> str`. Match templates from spec §3.7. Examples:
  - `create_appointment, {name=Ира, date=2026-05-08, time=14:30}` → `«запиши Ира на 2026-05-08 в 14:30»`
  - `update_note, {appointment_id=42, name=Ира, date=2026-05-08, time=14:00, note_text="френч"}` → `«добавь к записи Ира 2026-05-08 14:00 заметку: френч»`
- [ ] **Step 8.6** Implement `build_canonical`.
- [ ] **Step 8.7** Failing test for `decide_next(entities, today, repos) -> NormalizationResult`. Cases:
  - Empty entities → `kind="no_verb_detected"`
  - Full create entities → `kind="canonical_ready"`, canonical text matches
  - `cancel_appointment` with date but multiple appointments → `kind="needs_clarification"`, `question.field="appointment_ref"`, `question.editor="appointment_picker"`, options = appointments on date
  - `update_note` with appointment_id but no note text → `kind="needs_clarification"`, `question.field="note_text"`, `question.editor="text_input"`
- [ ] **Step 8.8** Implement `decide_next` and the `NormalizationResult` / `ClarifyQuestion` / `ClarifyOption` dataclasses (spec §3.1).
- [ ] **Step 8.9** ruff/mypy/pytest. Commit: `feat(intent): text-normalizer extract / decide_next / canonical builder`.

### Task 9: Appointment-picker keyboard

- [ ] **Step 9.1** Failing test: `appointment_picker_kb(options, tag)` returns inline keyboard with one row per option (`label`), each callback `IntakeCD(action="sb_pick", tag=..., index=i)`, plus a footer row `[❌ Отмена]` with `IntakeCD(action="cancel_edit", tag=...)`.
- [ ] **Step 9.2** Implement in `src/bot/keyboards/appointment_picker.py`.
- [ ] **Step 9.3** ruff/mypy/pytest. Commit: `feat(bot): appointment-picker keyboard for smart-fallback`.

### Task 10: Bot wiring — dispatch branch, store FSM, render question

- [ ] **Step 10.1** Failing test (in `tests/bot/test_smart_brain_flow.py` with stubbed LLM): when `LLM #1` returns `tool_name=None` and the normalizer returns `canonical_ready`, the second LLM call is made with the canonical text and `is_canonical=True`. (Use a counting fake LLM.)
- [ ] **Step 10.2** Failing test: when `LLM #1` returns None and normalizer returns `needs_clarification`, the bot does NOT call LLM #2; instead sets state `IntakePending.smart_brain_pick` (or `_text`), edits status message to the question prompt with the question's keyboard, stores `sb_verb`/`sb_entities`/`sb_msg_id`/`sb_field_being_asked` in FSM data.
- [ ] **Step 10.3** Failing test: when normalizer returns `no_verb_detected`, status is replaced with the existing «не понял» text. No FSM state set.
- [ ] **Step 10.4** Failing test (loop guard): even if LLM #2 also returns `tool_name=None`, the bot does NOT re-enter the normalizer; it shows «не понял».
- [ ] **Step 10.5** Implement: extend `_dispatch` in `src/bot/handlers/intake.py` along the lines of spec §3.6 pseudocode. Wrap the existing LLM call so we can branch on `tool_name=None`. Pass `is_canonical=True` only on the second call.
- [ ] **Step 10.6** Implement: helper `_render_sb_question(bot, chat_id, msg_id, question, tag)` that picks the right keyboard (`appointment_picker_kb`, `client_picker_kb`, `calendar_kb`, `time_picker_kb`, or text-input prompt with cancel button) and edits the status message accordingly.
- [ ] **Step 10.7** ruff/mypy/pytest. Commit: `feat(bot): dispatch branches into smart-brain when LLM #1 fails`.

### Task 11: Bot wiring — answer handlers (pick + text + voice + cancel)

- [ ] **Step 11.1** Failing test: while `IntakePending.smart_brain_pick`, callback `IntakeCD(action="sb_pick", index=i)` reads i'th option's `payload` from FSM-stashed `sb_question_options`, merges into `sb_entities`, calls `decide_next` again, branches: another `needs_clarification` → render new question; `canonical_ready` → call LLM #2; never re-enters extract().
- [ ] **Step 11.2** Implement `on_smart_brain_pick`. State filter: `IntakePending.smart_brain_pick`. Callback filter: `IntakeCD.filter(F.action == "sb_pick")`.
- [ ] **Step 11.3** Failing test: while `IntakePending.smart_brain_pick`, calendar pick (`CalendarCD(action="pick", iso_date=...)`) — same merge-and-decide flow but the value comes from the calendar callback instead of an option index.
- [ ] **Step 11.4** Implement `on_smart_brain_calendar_pick` and time-picker analogue. State-filtered.
- [ ] **Step 11.5** Failing test: while `IntakePending.smart_brain_text`, free text «френч» — value goes into `sb_entities[sb_field_being_asked]`, `decide_next` fires, branches as in 11.1.
- [ ] **Step 11.6** Implement `on_smart_brain_text` (state-filtered, `F.text`).
- [ ] **Step 11.7** Failing test: while `IntakePending.smart_brain_text`, voice — STT runs, transcript merges as text would. Same branch logic.
- [ ] **Step 11.8** Implement `on_smart_brain_voice` (state-filtered, `F.voice`).
- [ ] **Step 11.9** Failing test: cancel — `IntakeCD(action="cancel_edit")` while in either smart-brain state → `state.clear()` + status replaced with «❌ Отменено».
- [ ] **Step 11.10** Implement `on_smart_brain_cancel`.
- [ ] **Step 11.11** Add `~StateFilter(IntakePending.smart_brain_text)` to the existing `on_voice`/`on_text` filters in intake (same pattern as `editing_field_text`). Extend `_try_wizard_consume` to recognise the new state if needed.
- [ ] **Step 11.12** ruff/mypy/pytest. Commit: `feat(bot): smart-brain answer handlers (pick / text / voice / cancel)`.

### Task 12: System prompt — `is_canonical` flag + Layer A nudge

- [ ] **Step 12.1** Failing test: `build_system_prompt(..., is_canonical=False)` (default) does NOT contain the «текст уже нормализован» block.
- [ ] **Step 12.2** Failing test: `build_system_prompt(..., is_canonical=True)` contains the «текст уже нормализован» block at the end.
- [ ] **Step 12.3** Failing test: prompt always contains the Layer A nudge — «Если ты не уверен, на какую именно запись ссылается команда, всё равно вызывай инструмент с тем что знаешь — он сам уточнит».
- [ ] **Step 12.4** Implement: extend `build_system_prompt` in `src/services/intent/prompt.py`. Default `is_canonical=False`. Add Layer A nudge unconditionally.
- [ ] **Step 12.5** Plumb `is_canonical=True` through to LLM #2 in `_dispatch` (already covered in Task 10.5; double-check the wiring).
- [ ] **Step 12.6** ruff/mypy/pytest. Commit: `feat(intent): is_canonical prompt flag + Layer A nudge`.

### Task 13: End-to-end integration tests

- [ ] **Step 13.1** Test: «отмени завтрашнюю запись» — LLM #1 returns None, normalizer extracts verb=cancel, date=tomorrow, no name → if 0 appointments tomorrow → «не понял»; if 1 → canonical_ready → LLM #2 calls cancel; if 2+ → `appointment_picker` question, user picks → canonical_ready → LLM #2 calls cancel.
- [ ] **Step 13.2** Test: «добавь заметку на завтрашнюю запись» — two-step clarify: pick appointment, then text input → canonical → LLM #2 calls update_note.
- [ ] **Step 13.3** Test: «запиши Иру на завтра в 14» — LLM #1 returns None, normalizer extracts everything, `canonical_ready` → LLM #2 calls create_appointment.
- [ ] **Step 13.4** Test: «полная фигня без глаголов» → no_verb_detected → «не понял».
- [ ] **Step 13.5** Test: Layer A path — LLM #1 returns `cancel_appointment(date="2026-05-08")` directly; action returns CLARIFY with options — bot renders confirm-style clarify card (existing path). Smart brain NOT invoked.
- [ ] **Step 13.6** ruff/mypy/pytest. Commit: `test(bot): end-to-end smart-fallback integration`.

### Task 14: Docker rebuild + manual smoke

- [ ] **Step 14.1** `docker compose up -d --build bot` — verify clean startup logs.
- [ ] **Step 14.2** Manual smoke (Telegram, copyable test strings):
  - `отмени завтрашнюю запись` — expect picker if multiple, direct cancel-confirm if one.
  - `добавь заметку на завтрашнюю` — expect picker, then «Напиши заметку:».
  - `запиши Иру на завтра в 14:30 заметка френч` — expect single confirm-card.
  - `привет` — expect «не понял команду».
  - `покажи Иру` — expect «не понял команду» (acceptable: too ambiguous for keyword).
- [ ] **Step 14.3** Iterate on real-world phrases the user reports. Adjust vocab / extractors as needed.
- [ ] **Step 14.4** Once stable: commit any tuning, no merge to master yet (user reviews UX first).

---

## Open assumptions / things to verify in flight

- `gpt-oss-120b:free` reliably tool-calls on the canonical text. If LLM #2 starts missing too — we either harden the canonical templates (more structure) or push more burden onto Layer A.
- The denormalize dictionary (8 suffix rules) covers ≥95% of common forms in practice. If users say something exotic — we add rules; if it becomes a long tail — we revisit pymorphy2.
- Existing `editing_field_text` handler does NOT capture smart_brain_text events. Verify by reading the handler's state filter; the new state-filtered `on_smart_brain_text` should win because aiogram dispatches state-filtered handlers in registration order — register the new ones in front of the per-field-edit ones.

## Done definition

- All 14 tasks committed.
- 366 existing tests pass + ~30 new tests.
- ruff/mypy/pytest clean on every commit.
- Bot built and running in Docker.
- Manual smoke covers the 5 phrases in §14.2.
- User has tested «отмени завтрашнюю» and «добавь заметку на завтрашнюю» and confirmed the clarify flow feels right.
