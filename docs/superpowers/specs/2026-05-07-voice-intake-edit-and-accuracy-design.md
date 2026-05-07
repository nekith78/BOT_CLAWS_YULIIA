# Voice Intake — Per-field Edit & LLM Accuracy (Design)

> Brainstorm date: 2026-05-07
> Builds on: Plan #4 (voice intake) — already shipped on `plan/voice-intake`.

## Goal

Two improvements on top of the Plan #4 baseline:

1. **Per-field edit on the confirm-card.** When the bot parses a voice/text command into a structured action and shows a confirm card, the user can tap «✏️ Изменить дату / время / заметку / клиента / instagram» to fix one field instead of restarting the whole command.
2. **Few-shot examples in the LLM system prompt** so the free-tier `gpt-oss-120b` parses short Russian commands more reliably (chooses the right tool, fills correct args, doesn't drop into «не понял команду»).

Both improvements are about making voice/text intake feel reliable on a weak free model.

## Architecture context

Plan #4 introduced an `Action` registry (`services/intent/actions/`), an LLM dispatcher (`services/intent/llm.py` — currently OpenRouter → `gpt-oss-120b:free`), and an intake handler (`bot/handlers/intake.py`) that routes voice → STT → LLM → action. After `action.plan()` returns `CONFIRM`, intake renders a confirm card with three buttons: ✅ Сохранить, ✏️ Изменить, ❌ Отменить. The «Изменить» button currently dead-ends with «открой меню для ручного редактирования» — that's what this design replaces.

## Decisions (from brainstorm)

1. **Universal mechanism (D)**: each action declares which of its fields are editable; the confirm-card renders dynamically. New actions get edit-buttons for free.
2. **Per-type editors**: Date → inline calendar; Time → hybrid hour-min picker; Client → client picker (recent + search); Note / Instagram → text input.
3. **LLM accuracy approach A**: few-shot examples in the system prompt + per-action `description` examples. Whisper upgrade and retry-on-no-tool deferred until shown necessary.

---

## Section 1 — Data model: `EditableField` + `ActionResponse` extension

`ActionResponse` gains an optional list of editable fields, declared at CONFIRM time:

```python
@dataclass(frozen=True)
class EditableField:
    key: str          # payload key being edited: "date", "time", "client_name", "note", "instagram"
    label: str        # Russian button label: "Дата", "Время", "Клиент", "Заметка", "Instagram"
    editor: Literal["calendar", "time_picker", "client_picker", "text_input"]
    prompt_text: str | None  # only for editor="text_input": "Напиши заметку:"


@dataclass(frozen=True)
class ActionResponse:
    ...existing fields...
    editable_fields: list[EditableField] | None = None
```

Each action's `plan()` populates `editable_fields` from its current `pending_payload` when the result is `CONFIRM`. If the list is `None` or empty, the confirm-card behaves exactly as today (no per-field buttons) — backwards-compatible.

## Section 2 — Confirm-card layout

The intake handler renders the confirm-card with edit-buttons grouped 2-per-row above the standard footer:

```
<preview text>

[✏️ Имя клиента]   [✏️ Дата]
[✏️ Время]         [✏️ Заметка]
[✏️ Instagram]
[✅ Сохранить]
[✏️ Изменить полностью]   [❌ Отменить]
```

«✏️ Изменить полностью» preserves the existing «edit-flow handoff» button — currently a stub showing «открой меню вручную». This design does not change that stub; full FSM handoff with pre-filled fields stays as future work. The escape hatch when per-field edits aren't enough.

New callback data: `IntakeCD(action="edit_field", tag=tag, field=key)`. The `tag` is identical to the confirm-card tag — links to the same FSM-stashed `pending_payload`.

## Section 3 — Edit flows per editor type

State transitions for in-place editing.

### `calendar`

1. User taps `✏️ Изменить дату`.
2. Handler edits the confirm-card message → inline calendar (anchor = current date in payload).
3. User picks a date → existing `CalendarCD` callback fires → handler updates `pending_payload["date"]` (and any derived field like `starts_at_utc_iso`).
4. Handler calls `action.plan(ctx, merged_args)` again — **no LLM call** — and re-renders the confirm-card with the new value reflected in preview text.
5. State stays `IntakePending.confirming` throughout.

### `time_picker`

Same as calendar but with the hybrid time picker (hour grid → minute grid, with «другое время» wheel as fallback). Tap completes → update `pending_payload["time"]` → re-plan → re-render.

### `client_picker`

Same as calendar but with `client_picker_kb` (recent + search). On pick → update `pending_payload["client_id"]` and `pending_payload["client_name"]` → re-plan → re-render.

### `text_input`

1. User taps `✏️ Изменить заметку`.
2. Handler edits the message → `Напиши заметку:` with `[❌ Отмена]` inline button.
3. State changes to `IntakePending.editing_field_text`. FSM data carries `{tag, field_key, prompt_msg_id}`.
4. User sends a message:
   - **Text** → use as new value.
   - **Voice** → run STT → use transcript as new value (intentionally — voice typing is fine for note text).
5. Handler updates `pending_payload[field_key]` → re-plan → re-render confirm-card → state back to `IntakePending.confirming`.

### Cancel-during-edit

- For pickers (calendar / time / client) the existing «back/cancel» buttons of those keyboards return to the confirm-card with original payload (no changes applied).
- For `text_input`, the `❌ Отмена` button returns to confirm-card unchanged.

### Voice / text intake during editing

- During structured pickers (calendar / time / client) — voice/text intake interrupts: cancels the edit-flow and runs the new command. This matches the existing «voice always interrupts active FSM» policy in `_cancel_active_state`.
- During `text_input` editing — the next user message becomes the field value (point 4 above). To break out and start a new command, user must tap `❌ Отмена` first.

## Section 4 — Per-action `editable_fields` lists

| Action | Editable fields |
|---|---|
| `create_appointment` | client_name (client_picker), date (calendar), time (time_picker), note (text_input), instagram (text_input) |
| `move_appointment` | new_date (calendar), new_time (time_picker) |
| `edit_note` | note (text_input) |
| `cancel_appointment` | none — confirm-card without edit buttons |
| `delete_client` | none — confirm-card without edit buttons |
| `list_appointments`, `list_client_history` | n/a — read-only, no confirm-card |

For `cancel_appointment` / `delete_client`, the only meaningful «edit» would be to choose a different target. That's already covered by CLARIFY (when ambiguous) or re-issuing the command (when the wrong one was picked).

For `move_appointment`, only the new date/time are editable. To change which appointment is being moved (the source), the user cancels and re-issues the command — the source identity is fixed at confirm time.

## Section 5 — LLM accuracy: few-shot in system prompt

Add a `ПРИМЕРЫ` block to `prompt.py` after the existing rules:

```
ПРИМЕРЫ (как переводить речь в tool call):
«запиши Иру на завтра в 14:30» → create_appointment(client_name="Ира", date=<today+1>, time="14:30")
«запиши Олега завтра вечером» → create_appointment(client_name="Олег", date=<today+1>, time="18:00")
«запиши Машу на субботу в три» → create_appointment(client_name="Маша", date=<ближайшая суббота>, time="15:00")
«покажи записи на сегодня» → list_appointments(period="today")
«покажи историю Кости» → list_client_history(client_name="Костя")
«перенеси Олега на 16:00» → move_appointment(client_name="Олег", new_time="16:00")
«отмени запись Иры» → cancel_appointment(client_name="Ира")
«добавь к записи Иры заметку френч» → edit_note(client_name="Ира", note="френч")
«удали Иру» → delete_client(client_name="Ира")
«привет», «спасибо», «как дела» → НЕ вызывать никакую tool
```

Estimated +250 tokens to system prompt. Free tier doesn't ratelimit by token count, only by request count, so this is essentially free in cost terms. Latency cost ~0.3 sec/request — invisible to user.

Each Action's `description` field is reviewed and expanded with 1–2 representative phrases if not already concrete enough. Reuses the same examples to avoid duplication mismatch.

## Section 6 — Testing

**Unit tests**:

- `EditableField` dataclass smoke (frozen, equality).
- For each editing-capable action: `plan()` returns expected `editable_fields` at CONFIRM and `None` at FAIL / CLARIFY.
- Re-plan after merging an updated payload returns the same set of editable_fields with the new value reflected in preview text.

**Integration tests** (mocked Telegram bot + LLM, real DB session):

- Tap `edit_field` → handler renders correct editor (one test per editor type).
- Calendar pick → re-plan called with merged date.
- Time pick → re-plan with merged time.
- Client pick → re-plan with merged client_id + client_name.
- `text_input` flow → FSM state transitions through full edit cycle (text and voice paths).
- `❌ Отмена` during edit → returns to original confirm-card with payload unchanged.

**Manual smoke** (after deploy):

1. Voice «запиши Иру на завтра в десять» → confirm-card with 5 edit buttons.
2. Tap `✏️ Изменить дату` → calendar appears → pick another day → confirm-card refreshed with new date.
3. Tap `✏️ Изменить заметку` → bot prompts for text → send «френч» → confirm-card has `📝 френч`.
4. Tap `✅ Сохранить` → запись создана с обновлёнными полями. /quota shows 1 LLM call used (only the initial parse).
5. «привет» → bot still shows help (no tool picked).
6. «запиши Машу на субботу в три» → date is the nearest Saturday and time is 15:00, not 03:00.

## Section 7 — File-level scope of changes

- `src/services/intent/types.py` — `EditableField` dataclass + extend `ActionResponse`.
- `src/services/intent/prompt.py` — add `ПРИМЕРЫ` block.
- `src/services/intent/actions/create_appointment.py` — populate `editable_fields` on CONFIRM.
- `src/services/intent/actions/move_appointment.py` — same.
- `src/services/intent/actions/edit_note.py` — same.
- `src/bot/handlers/intake.py` — handle `IntakeCD(action="edit_field")` callback, manage edit-flow states, dispatch into per-editor sub-flows.
- `src/bot/keyboards/confirm_card.py` — render edit buttons dynamically from `editable_fields`.
- `src/bot/states.py` — add `IntakePending.editing_field_text` state.
- `src/bot/callback_data.py` — `IntakeCD.action` adds `"edit_field"`; `IntakeCD.field: str = ""` new optional payload.
- Tests in mirroring locations.

Estimated scope: ~10–15 commits, ~3–5 hours of subagent-driven implementation.

## Out of scope

- Whisper upgrade `small` → `medium` (deferred — brainstorm option B; revisit if smoke shows STT errors).
- Auto-retry on no-tool LLM responses (brainstorm option C; too quota-hungry on free tier).
- Editing the source appointment of `move_appointment` / `cancel_appointment` / `edit_note` (cancel and re-issue covers it).
- Editing turn history / `context_snapshot` itself (handled by `recent_turns` infrastructure).
- Per-field edit for read-only actions (`list_appointments`, `list_client_history` — n/a).
- Real handoff to AddAppointment FSM from «✏️ Изменить полностью» (still a stub; future work).

## Spec self-review notes

- Placeholders: none.
- Internal consistency: Section 1 model + Section 2 layout + Section 3 flows are coherent. Section 4 table matches Section 3 editor types. Section 5 doesn't conflict with the rest.
- Scope: focused on per-field edit + few-shot prompt; no creep.
- Ambiguity: «✏️ Изменить полностью» behavior is explicit (stub preserved). Voice-during-text-input is explicit (becomes value). Voice-during-picker is explicit (interrupts).
