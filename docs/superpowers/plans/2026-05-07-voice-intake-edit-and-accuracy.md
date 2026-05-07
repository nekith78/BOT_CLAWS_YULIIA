# Voice Intake — Per-field Edit & LLM Accuracy (Plan #5)

> **For agentic workers:** TDD per task — failing test → impl → ruff/mypy clean → commit. Storage-first; service layer next; bot/handlers last. Stay on branch `plan/voice-intake-edit` (forked from `plan/voice-intake`).

> Spec: [docs/superpowers/specs/2026-05-07-voice-intake-edit-and-accuracy-design.md](../specs/2026-05-07-voice-intake-edit-and-accuracy-design.md)

**Goal:** ship two improvements on top of the Plan #4 baseline:
1. Per-field edit on the confirm-card so each action can declare which payload fields are user-editable; confirm-card renders edit buttons dynamically; tapping an edit button opens the right editor (calendar / time-picker / client-picker / text-input), which on completion re-plans the action with the merged payload.
2. Few-shot `ПРИМЕРЫ` block in the system prompt so the free-tier `gpt-oss-120b` model picks tools and args more reliably for short Russian commands.

**Architecture context:** Plan #4 closed and merged into `plan/voice-intake`. Action registry (`services/intent/actions/`), LLM dispatcher (OpenRouter → `gpt-oss-120b:free`), intake handler (`bot/handlers/intake.py`) all in place. Confirm-card today has fixed three buttons (✅ / ✏️ / ❌); ✏️ is a stub that tells user to use manual menu. This plan replaces the stub with structured per-field editing.

**Tech stack additions:** none — reuses existing keyboards (`calendar_kb`, `time_picker_kb` + `time_part_picker_kb`, `client_picker_kb`).

**Prerequisites:**
- master + `plan/voice-intake` ahead with intake / actions / OpenRouter wired and working in Docker.
- All 290 tests green, ruff/mypy clean.

**Decisions (from brainstorm 2026-05-07):**
1. **Universal mechanism**: each action declares editable fields; confirm-card renders dynamically.
2. **Per-type editors**: calendar / time_picker / client_picker / text_input.
3. **Few-shot prompt**: ~10 examples for the LLM, ~250 tokens per request — quota-neutral.

---

## File Structure

| Путь | Назначение |
|---|---|
| `src/services/intent/types.py` | _Modify_ — add `EditableField` + extend `ActionResponse` |
| `src/services/intent/prompt.py` | _Modify_ — `ПРИМЕРЫ` block |
| `src/services/intent/actions/create_appointment.py` | _Modify_ — populate `editable_fields` on CONFIRM |
| `src/services/intent/actions/move_appointment.py` | _Modify_ — same |
| `src/services/intent/actions/edit_note.py` | _Modify_ — same |
| `src/bot/states.py` | _Modify_ — add `IntakePending.editing_field_text` |
| `src/bot/callback_data.py` | _Modify_ — `IntakeCD` gains `action="edit_field"` + `field: str` |
| `src/bot/keyboards/confirm_card.py` | _Modify_ — render edit buttons from `editable_fields` |
| `src/bot/handlers/intake.py` | _Modify_ — `edit_field` callback router + per-editor sub-flows + text-input state |
| `tests/...` | mirror tests across modified paths |

---

## Tasks

### Task 1: Branch + foundation (types, callbacks, state)

- [ ] **Step 1.1** Create branch `plan/voice-intake-edit` from `plan/voice-intake`.
- [ ] **Step 1.2** Failing test: `EditableField` is a frozen dataclass with `key`, `label`, `editor`, `prompt_text` fields; `ActionResponse(editable_fields=...)` round-trips.
- [ ] **Step 1.3** Implement `EditableField` + `ActionResponse.editable_fields: list[EditableField] | None = None` in `services/intent/types.py`. Editor literal: `"calendar" | "time_picker" | "client_picker" | "text_input"`.
- [ ] **Step 1.4** Failing test on `IntakeCD.unpack` for `action="edit_field"` with `field="date"` and `tag="abc"`.
- [ ] **Step 1.5** In `src/bot/callback_data.py`: extend `IntakeCD.action` literal with `"edit_field"`, add `field: str = ""` payload.
- [ ] **Step 1.6** In `src/bot/states.py`: add `IntakePending.editing_field_text` state.
- [ ] **Step 1.7** ruff/mypy/pytest. Commit: `feat(intent): EditableField data model + edit_field callback`.

### Task 2: Confirm-card keyboard renders dynamic edit buttons

- [ ] **Step 2.1** Failing test: `confirm_card_kb(tag, editable_fields=None)` returns the existing 3-button layout.
- [ ] **Step 2.2** Failing test: `confirm_card_kb(tag, editable_fields=[<2 fields>])` returns 1 row with 2 edit-buttons, then ✅ row, then `[✏️ Изменить полностью][❌ Отменить]` row.
- [ ] **Step 2.3** Failing test: 5 fields produce 3 edit-rows (2-2-1 packing).
- [ ] **Step 2.4** Implement: in `src/bot/keyboards/confirm_card.py`, accept optional `editable_fields` and render `[✏️ <label>]` buttons (callback `IntakeCD(action="edit_field", tag=..., field=key)`), packed 2 per row, above the standard footer.
- [ ] **Step 2.5** Existing intake handler: pass `response.editable_fields` to `confirm_card_kb` when rendering. (No actions populate yet — kb gracefully shows old layout.)
- [ ] **Step 2.6** ruff/mypy/pytest. Commit: `feat(bot): confirm-card renders dynamic edit buttons`.

### Task 3: Few-shot ПРИМЕРЫ in system prompt

- [ ] **Step 3.1** Failing test: `build_system_prompt(...)` output contains the string `«запиши Иру на завтра в 14:30»` and lists tools for create / list / move / cancel / note / history / delete.
- [ ] **Step 3.2** Add a `ПРИМЕРЫ` section in `src/services/intent/prompt.py` after the rules block (~10 examples covering all 7 actions + chitchat negative example).
- [ ] **Step 3.3** Review each Action's `description` field; if examples are weak, expand by 1–2 phrases. Keep style consistent across Actions.
- [ ] **Step 3.4** ruff/mypy/pytest. Commit: `feat(intent): few-shot ПРИМЕРЫ in system prompt`.

### Task 4: `create_appointment.editable_fields` on CONFIRM

- [ ] **Step 4.1** Failing test: when `plan()` returns CONFIRM with full payload, `editable_fields` lists 5 entries: client_name (client_picker), date (calendar), time (time_picker), note (text_input), instagram (text_input).
- [ ] **Step 4.2** Failing test: when `plan()` returns FAIL or CLARIFY, `editable_fields` is None.
- [ ] **Step 4.3** Implement in `create_appointment.py`. `prompt_text` strings: `«Напиши заметку:»`, `«Напиши Instagram-ник (без @):»`.
- [ ] **Step 4.4** ruff/mypy/pytest. Commit: `feat(intent): create_appointment declares editable_fields`.

### Task 5: `move_appointment` + `edit_note` editable_fields

- [ ] **Step 5.1** Failing test: `move_appointment.plan()` CONFIRM has 2 fields: new_date (calendar), new_time (time_picker).
- [ ] **Step 5.2** Implement in `move_appointment.py`.
- [ ] **Step 5.3** Failing test: `edit_note.plan()` CONFIRM has 1 field: note (text_input).
- [ ] **Step 5.4** Implement in `edit_note.py`.
- [ ] **Step 5.5** Sanity tests: `cancel_appointment.plan()` and `delete_client.plan()` CONFIRM have `editable_fields=None` (no change in behavior).
- [ ] **Step 5.6** ruff/mypy/pytest. Commit: `feat(intent): move_appointment + edit_note declare editable_fields`.

### Task 6: Calendar edit-flow handler

- [ ] **Step 6.1** Define re-plan helper in `intake.py`: `_replan_with_merged_args(callback, action_name, merged_args, msg_id)` — fetches Action, opens session, calls `action.plan(ctx, merged_args)`, renders response by replacing message contents (treats msg_id as the status message).
- [ ] **Step 6.2** Failing integration test: tap `IntakeCD(action="edit_field", field="date", tag=...)` for an action where `editable_fields` includes a calendar field → handler edits message to calendar keyboard with current date as anchor.
- [ ] **Step 6.3** Implement: new callback handler `on_edit_field` (matching `IntakeCD(action="edit_field")`), looks at FSM-stored payload + action's `editable_fields` to find the field's editor type. For `editor=calendar`, edit message to `calendar_kb(anchor=current_date, counts=..., back_callback_data=<intake-back-tag>)`. Persist `editing_field_meta` in FSM data: `{tag, field_key, action_name}`.
- [ ] **Step 6.4** Failing test: `CalendarCD(action="pick", iso_date=...)` while `editing_field_meta` is set → handler reads field_key from FSM, merges into payload, calls re-plan helper, restores confirm-card.
- [ ] **Step 6.5** Implement the calendar-pick interception. Use a state filter (`IntakePending.confirming` + the FSM data marker) to avoid colliding with the existing AddAppointment / lists calendar handlers.
- [ ] **Step 6.6** Cancel button on calendar (`back_callback_data`) → restore confirm-card from FSM payload (no merge).
- [ ] **Step 6.7** ruff/mypy/pytest. Commit: `feat(bot): per-field edit — calendar editor`.

### Task 7: Time-picker edit-flow handler

- [ ] **Step 7.1** Failing test: tap `IntakeCD(action="edit_field", field="time")` → handler edits message to time grid.
- [ ] **Step 7.2** Implement: for `editor=time_picker`, edit message to `time_picker_kb()`. Persist `editing_field_meta` as in Task 6.
- [ ] **Step 7.3** Failing test: `TimeCD(hhmm="14:30")` while editing_field_meta is set → handler merges into payload, re-plans, restores confirm-card.
- [ ] **Step 7.4** Implement. Same pattern as calendar — state filter + FSM data marker.
- [ ] **Step 7.5** Time-part custom flow: `TimePartCD(action="hour"|"minute"|...)` flows back through the hybrid hour→minute screens then commits via the same merge-and-replan path.
- [ ] **Step 7.6** ruff/mypy/pytest. Commit: `feat(bot): per-field edit — time-picker editor`.

### Task 8: Client-picker edit-flow handler

- [ ] **Step 8.1** Failing test: tap `IntakeCD(action="edit_field", field="client_name")` → handler edits message to `client_picker_kb` with recent clients.
- [ ] **Step 8.2** Implement: for `editor=client_picker`, edit message to `client_picker_kb(recent=...)`. Reuse the existing client-search mini-flow if user types a search query.
- [ ] **Step 8.3** Failing test: `ClientCD(action="pick", client_id=...)` while editing → handler fetches client, merges client_id + client_name into payload, re-plans, restores confirm-card.
- [ ] **Step 8.4** Implement. Same state-filter approach.
- [ ] **Step 8.5** Decide & document: a client picked here always exists in DB, so we never trigger «новый клиент» path mid-edit. If user wants to create a new one, they cancel + re-issue with a new name.
- [ ] **Step 8.6** ruff/mypy/pytest. Commit: `feat(bot): per-field edit — client-picker editor`.

### Task 9: Text-input edit-flow handler

- [ ] **Step 9.1** Failing test: tap `IntakeCD(action="edit_field", field="note")` → handler edits message to `<prompt_text>` with `[❌ Отмена]` button; FSM state becomes `IntakePending.editing_field_text` with `{tag, field_key, action_name}` in data.
- [ ] **Step 9.2** Implement.
- [ ] **Step 9.3** Failing test: in `IntakePending.editing_field_text`, sending text «френч» → handler updates payload, re-plans, restores confirm-card with note=«френч»; state back to `IntakePending.confirming`.
- [ ] **Step 9.4** Implement.
- [ ] **Step 9.5** Failing test: in `editing_field_text`, sending voice → STT transcribes → use as field value (same merge-replan path).
- [ ] **Step 9.6** Implement voice path inside the editing_field_text handler (reuse existing STT helper from `on_voice`).
- [ ] **Step 9.7** Failing test: tap `❌ Отмена` while editing_field_text → returns to confirm-card unchanged.
- [ ] **Step 9.8** Implement: separate `IntakeCD(action="cancel_edit", tag=tag)` — or piggyback on existing `cancel` action with state filter. Cleanest: add `cancel_edit` literal to keep the semantic explicit.
- [ ] **Step 9.9** ruff/mypy/pytest. Commit: `feat(bot): per-field edit — text-input editor`.

### Task 10: Replan helper unification + edge cases

- [ ] **Step 10.1** Refactor pass: extract a single `_apply_edit_and_replan(handler_ctx, field_key, new_value)` helper that:
  1. Loads payload + action_name + tag from FSM data.
  2. Merges `{field_key: new_value}` into payload (and any derived fields, e.g., for date+time → starts_at_utc_iso).
  3. Calls `action.plan(ctx, merged_args)` (no LLM call).
  4. Calls `_render` with the resulting `ActionResponse`, reusing the existing message_id.
  5. Restores `IntakePending.confirming` state.
- [ ] **Step 10.2** Each picker / text-input handler from Tasks 6-9 calls this helper. Drop duplicated code.
- [ ] **Step 10.3** Failing test: changing `date` for `create_appointment` re-derives `starts_at_utc_iso` correctly (no stale UTC field after edit).
- [ ] **Step 10.4** ruff/mypy/pytest. Commit: `refactor(bot): unify per-field edit replan helper`.

### Task 11: Docker smoke + final review + merge

- [ ] **Step 11.1** All 290+ tests green, ruff/mypy clean.
- [ ] **Step 11.2** Smoke in Docker:
   1. Voice «запиши Иру на завтра в десять» → confirm-card shows 5 edit buttons.
   2. `✏️ Изменить дату` → calendar → pick day → confirm refreshed.
   3. `✏️ Изменить время` → grid → pick → confirm refreshed.
   4. `✏️ Изменить клиента` → client picker → pick → confirm refreshed.
   5. `✏️ Изменить заметку` → bot prompts → send «френч» → confirm shows 📝 френч.
   6. `✏️ Изменить заметку` → send voice «гель» → confirm shows 📝 гель.
   7. `✏️ Изменить заметку` → tap ❌ Отмена → confirm-card unchanged.
   8. `✅ Сохранить` → запись создана с обновлёнными полями.
   9. `move_appointment` flow: voice «перенеси Иру на 16:00» → 2 edit buttons → tap время → grid → confirm refreshed.
   10. `«запиши Машу на субботу в три»` → confirm with date=Saturday, time=15:00 (few-shot prompt).
   11. `«привет»` → help message (no tool picked).
   12. `/quota` increment by 1 per intake voice/text command (not per edit).
- [ ] **Step 11.3** Fast-forward `plan/voice-intake-edit` → `plan/voice-intake` → `master`. Push.
- [ ] **Step 11.4** Update CLAUDE.md if there are new patterns worth documenting (e.g., Action.editable_fields contract).

---

## Open questions (resolve in implementation)

1. **Existing keyboards and their callback ownership.** `calendar_kb` is used by `add_appointment`, `lists`, `appointment_card` flows; each handles `CalendarCD` under its own state. We need a state-filtered `CalendarCD` handler in intake without breaking the others. Likely solution: filter on `IntakePending.confirming` + FSM data marker `editing_field_meta`. If aiogram routing already prefers state-filtered handlers, no collision.
2. **Re-plan with derived fields.** `create_appointment` payload has both `date`/`time` and `starts_at_utc_iso`. After editing date alone, the helper must recompute starts_at_utc_iso. Pattern: action's `plan(ctx, args)` accepts both `date`+`time` AND derives starts_at internally — so we pass merged args without starts_at and let plan derive.
3. **Voice during text-input editor.** Confirm in Task 9 that STT-transcribed voice goes directly into the field value as text. No special escaping needed — the field is plain string.
4. **«✏️ Изменить полностью» button.** Stays as the existing stub. If future work implements real handoff to AddAppointment FSM, that's a separate plan.

---

## Testing plan (high-level)

- **Unit**: `EditableField` smoke; per-action `editable_fields` enumeration; helpful preview text after merge.
- **Integration**: handler tests with mocked Telegram bot — full edit-flow per editor type; cancel paths; voice during text-input.
- **Smoke (manual)**: Task 11.2 above.

## Estimated scope

11 tasks × ~30–60 min each ≈ 6–10 hours of subagent-driven implementation. Comparable to Plan #4 Phase 4 (intake handler).

---

## Backwards-compat / migration

- No DB migrations.
- ActionResponse defaults `editable_fields=None` — actions that don't populate it (cancel, delete, list, history) keep current behavior bit-exact.
- Existing confirm-card (without editable_fields) is unchanged in layout — Task 2 falls back to old keyboard when list is None/empty.
- Few-shot prompt block adds tokens but no semantic regression (just more guidance).
