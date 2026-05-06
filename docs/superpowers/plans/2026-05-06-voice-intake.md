# Voice Intake & Universal Command Parser (Plan #4)

> **For agentic workers:** TDD per task — failing test → impl → ruff/mypy clean → commit. Storage-first; service layer next; bot/handlers last.

**Goal:** дать второй способ управления ботом помимо кнопок — голосом или свободным текстом. Команды покрывают все основные функции бота: создание/редактирование/перенос/отмена записи, просмотр списков и истории клиента, удаление клиента. Архитектура — registry-pattern: каждое действие декларирует JSON-схему, LLM выбирает action через function-calling, новое действие добавляется одним файлом и автоматически становится доступным голосом и текстом.

**Architecture context:** Plan #3 закрыт и в `master` (commit `617f454`). Foundation, Booking, Notifications работают. Текущий парсер в `services/parser/text_parser.py` — узкий regex для `/add YYYY-MM-DD HH:MM Имя`. Этот плагин остаётся как fallback для строгого формата; основной путь команд — через новый LLM-парсер.

**Tech stack additions:**
- `faster-whisper` (CTranslate2-port Whisper) — локальный STT, бесплатный, модель `small`. +~500 МБ к Docker-образу.
- `openai` SDK — уже есть, нужен fallback STT (Whisper API) и fallback LLM (gpt-4o-mini).
- `google-genai` SDK — Gemini Flash 2.5 как default LLM (бесплатный tier).
- В `Settings`: `STT_PROVIDER` (`faster_whisper`/`openai_whisper`), `LLM_PROVIDER` (`gemini`/`openai_mini`/`anthropic_haiku`), `LLM_MODEL` (override при необходимости), `VOICE_MAX_DURATION_SEC` (60), `WHISPER_MODEL_SIZE` (`small`).

**Prerequisites:**
- master содержит Plan #3 notifications.
- Все 189 тестов зелёные, ruff/mypy clean.
- В `.env` есть `OPENAI_API_KEY` (для fallback). Для default — `GEMINI_API_KEY` (получить на ai.google.dev, бесплатно).

**Decisions (согласовано с пользователем):**

1. **Скоуп голосом/текстом**: создание, перенос, заметка, отмена записи; список записей (today/tomorrow/week/month/конкретная дата); история клиента; удаление клиента. Notify-rules toggle и прочая мелочёвка — только кнопками.
2. **Один парсер на голос и текст**: voice → STT → текст → парсер; текст → парсер. Свободный текст в чате (без префиксов) тоже парсится — голос/текст/кнопки взаимозаменяемы.
3. **Registry-pattern**: каждое действие — это класс с `name`, `description`, `confirm_required`, JSON-схемой аргументов и async-методом `run(ctx, args)`. LLM получает список tools из реестра и делает function-call. Новое действие = новый файл в `services/intent/actions/` + регистрация — и оно сразу доступно голосом.
4. **STT default — faster-whisper `small`** (free, локально, +500 МБ образ). Fallback — OpenAI Whisper API через `STT_PROVIDER=openai_whisper`.
5. **LLM default — Gemini Flash 2.5** (free tier 1500 RPD). Fallback — gpt-4o-mini, опционально Anthropic Haiku.
6. **Confirm UX**: для destructive действий (create/move/note/cancel/delete) показываем preview-card «<суть действия>?» с кнопками `[✅ Сохранить] [✏️ Изменить] [❌ Отменить]`. Для read-only (list/history) — сразу открываем тот же экран что и кнопка `📋 Записи`/«История» (с тапабельными карточками). Удаление клиента — двойное подтверждение (как в текущем UI).
7. **Partial-understand**: если LLM разобрал часть полей (например, клиент + дата, но без времени) — бот показывает то что понял + кнопочный picker для недостающих полей. Не отклоняем без причины.
8. **Disambiguation**: если по имени матчатся 2+ клиента — кнопочный список «Кого имеешь в виду — Ира #1 (@ira_nails) / Ира #2». Если для action нужна конкретная запись (move/cancel/note) и подходит >1 — список записей кнопками.
9. **No-tool-call** (LLM не выбрал ни одно действие, например «привет») — отвечаем «Не понял команду, попробуй переписать или сделать вручную» + краткий список доступных команд.
10. **Voice/text внутри активного FSM**: автоматически отменяем текущий wizard (`finalize` с `❌ Отменено`) и стартуем парсер. Юзер всегда может перебить голосом.
11. **Лимит длительности voice** — 60 сек (защита от случайных длинных сообщений). Длиннее — отбой с подсказкой.
12. **Privacy**: faster-whisper локально; никакое аудио не уходит в облако в default-конфиге. Транскрибт уходит в Gemini/OpenAI — это компромисс за качество распознавания интента.

---

## Architecture overview

```
Telegram update
   ├── voice (or audio note)         text (free-form, без активного FSM)
   │       │                                │
   │       ▼                                │
   │   STTProvider.transcribe()             │
   │       │                                │
   │       └──────► transcript ◄────────────┘
   │                    │
   │                    ▼
   │            LLMProvider.parse_intent(text, tools=registry.tools())
   │                    │
   │                    ▼
   │            ParsedIntent(tool_name, args)
   │                    │
   │            ┌───────┴───────┐
   │            │               │
   │            ▼               ▼
   │   tool_name=None       tool_name="..."
   │   (no match)               │
   │      │                     ▼
   │      ▼               registry.get(name).run(ctx, args)
   │   "не понял"               │
   │   + краткий                ▼
   │   help                ActionResponse
   │                            │
   │                ┌───────────┼───────────┬─────────────┐
   │                ▼           ▼           ▼             ▼
   │          EXECUTED      CONFIRM     CLARIFY         FAIL
   │       (read-only       (preview-   (disambig.   (e.g. время
   │        result          card +      buttons)      в прошлом —
   │        sent)           confirm-                  ошибка)
   │                        buttons)
```

---

## File Structure

| Путь | Назначение |
|---|---|
| `src/services/voice/__init__.py` | _Modify_ — re-exports |
| `src/services/voice/stt.py` | `STTProvider` Protocol + dispatcher по `STT_PROVIDER` |
| `src/services/voice/faster_whisper_stt.py` | Локальный faster-whisper провайдер |
| `src/services/voice/openai_whisper_stt.py` | Whisper API fallback |
| `src/services/intent/__init__.py` | re-exports для use в handler'ах |
| `src/services/intent/registry.py` | `ActionRegistry`, регистрация всех действий, генерация tools-list для LLM |
| `src/services/intent/types.py` | `Action` Protocol, `ActionContext`, `ActionResponse`, `ActionResult` enum, `ParsedIntent` |
| `src/services/intent/llm.py` | `LLMProvider` Protocol + dispatcher |
| `src/services/intent/llm_gemini.py` | Gemini Flash провайдер |
| `src/services/intent/llm_openai.py` | OpenAI gpt-4o-mini провайдер |
| `src/services/intent/llm_anthropic.py` | _optional_ — Anthropic Haiku (если попросим) |
| `src/services/intent/prompt.py` | System-prompt: «ты ассистент бота-расписания, выбери tool…» + правила относительных дат («завтра» = today+1 в OWNER_TZ) |
| `src/services/intent/actions/create_appointment.py` | Create action |
| `src/services/intent/actions/list_appointments.py` | List action |
| `src/services/intent/actions/move_appointment.py` | Move action |
| `src/services/intent/actions/cancel_appointment.py` | Cancel action |
| `src/services/intent/actions/edit_note.py` | Note edit action |
| `src/services/intent/actions/list_client_history.py` | History action |
| `src/services/intent/actions/delete_client.py` | Delete client action |
| `src/services/intent/resolvers.py` | Helpers: `resolve_client(name)` → list[Client] (для disambiguation), `resolve_appointment(client_id, date_hint, time_hint)` → list[Appointment] |
| `src/bot/handlers/intake.py` | `@router.message(F.voice)` + `@router.message(F.text & ~commands)` — единая точка входа |
| `src/bot/keyboards/confirm_card.py` | `[✅ Сохранить] [✏️ Изменить] [❌ Отменить]` (унифицированный конфирм для всех destructive actions) |
| `src/bot/keyboards/intake_help.py` | Подсказка-меню после "не понял команду" |
| `src/bot/callback_data.py` | _Modify_ — `IntakeCD` (action=confirm/edit/cancel/clarify, tag — короткий идентификатор pending action) |
| `src/bot/states.py` | _Modify_ — `IntakePending` group: `confirming`, `clarifying` |
| `src/config.py` | _Modify_ — добавить `STT_PROVIDER`, `LLM_PROVIDER`, `GEMINI_API_KEY`, `WHISPER_MODEL_SIZE`, `VOICE_MAX_DURATION_SEC`. Расширить `model_validator` чтобы fail fast при пустом ключе нужного провайдера. |
| `.env.example` | _Modify_ — новые переменные |
| `Dockerfile` | _Modify_ — добавить системные deps для faster-whisper (libgomp, ffmpeg для voice→wav) |
| `pyproject.toml` | _Modify_ — добавить `faster-whisper`, `google-genai` |
| `tests/services/intent/...` | Тесты на каждый action (mock LLM, mock session) |
| `tests/services/voice/...` | Тесты на STT (mock backends) |
| `tests/bot/handlers/test_intake.py` | E2E на handler с замокенным STT+LLM |

---

## Action protocol (закрепляем структуру)

```python
# services/intent/types.py
class ActionResult(StrEnum):
    EXECUTED = "executed"   # выполнено, send результат
    CONFIRM  = "confirm"    # показать confirm-card
    CLARIFY  = "clarify"    # disambiguation buttons
    FAIL     = "fail"       # ошибка с понятным текстом

@dataclass(frozen=True)
class ActionResponse:
    result: ActionResult
    text: str
    keyboard: InlineKeyboardMarkup | None = None
    pending_payload: dict[str, Any] | None = None  # сохраняется в FSM до confirm/clarify

@dataclass(frozen=True)
class ActionContext:
    session: AsyncSession
    bot: Bot
    chat_id: int
    state: FSMContext
    scheduler: AsyncIOScheduler | None
    notify_runner: Any
    tz: ZoneInfo
    now_utc: datetime  # naive UTC, как в остальных сервисах

class Action(Protocol):
    name: str
    description: str
    confirm_required: bool
    params_schema: dict[str, Any]  # JSON-schema, скармливается LLM как tool

    async def plan(self, ctx: ActionContext, args: dict[str, Any]) -> ActionResponse: ...
    async def execute(self, ctx: ActionContext, payload: dict[str, Any]) -> ActionResponse: ...
```

`plan` вызывается сразу после парсинга — собирает preview, валидирует args, делает disambiguation если нужно. `execute` — после кнопки `✅ Сохранить` (берёт `pending_payload`).

Read-only actions (`list_appointments`, `list_client_history`) реализуют `confirm_required=False` и в `plan` сразу возвращают `EXECUTED` — `execute` не вызывается.

---

## Tasks

### Task 1: Branch + конфиг + .env

- [ ] **Step 1.1** Создать ветку `plan/voice-intake` от master.
- [ ] **Step 1.2** В `pyproject.toml` добавить `faster-whisper = "^1.0"`, `google-genai = "^0.5"`. `poetry lock && poetry install`.
- [ ] **Step 1.3** В `.env.example` добавить: `STT_PROVIDER=faster_whisper`, `WHISPER_MODEL_SIZE=small`, `VOICE_MAX_DURATION_SEC=60`, `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=`. Закомментированные fallback'ы для `openai_whisper`/`openai_mini`/`anthropic_haiku`.
- [ ] **Step 1.4** В `src/config.py` расширить `Settings` (новые поля + `model_validator` — для default `gemini` требовать `GEMINI_API_KEY`). Тест на validator (failing → impl).
- [ ] **Step 1.5** В `Dockerfile` добавить `apt-get install -y ffmpeg libgomp1` (нужно faster-whisper).
- [ ] **Step 1.6** ruff/mypy/pytest. Commit: `chore(config): add STT/LLM provider settings + .env entries`.

### Task 2: STT abstraction + faster-whisper provider

- [ ] **Step 2.1** Создать `src/services/voice/stt.py` с `STTProvider` Protocol (`async transcribe(audio: bytes, mime: str, *, language: str) -> str`) и `get_stt(settings)` dispatcher.
- [ ] **Step 2.2** Создать `src/services/voice/faster_whisper_stt.py`. На init — загрузить модель один раз (`WhisperModel("small", compute_type="int8")`). В `transcribe` — конвертировать ogg→wav через ffmpeg-pipe, прогнать через модель, вернуть текст. Указать `language="ru"`.
- [ ] **Step 2.3** Тесты: с реальным фиксированным ogg-файлом (короткий тестовый «запиши Иру на завтра в четырнадцать тридцать»). Проверить что транскрипт содержит ключевые слова (без точного match — модель недетерминирована).
   - Тест опционально помечен `@pytest.mark.slow` — может медленно идти на CI.
- [ ] **Step 2.4** ruff/mypy/pytest. Commit: `feat(voice): faster-whisper STT provider`.

### Task 3: STT fallback — OpenAI Whisper API

- [ ] **Step 3.1** `src/services/voice/openai_whisper_stt.py` — обёртка над `openai.audio.transcriptions.create`. `language="ru"`, `response_format="text"`.
- [ ] **Step 3.2** Тест с моком `openai` SDK.
- [ ] **Step 3.3** ruff/mypy/pytest. Commit: `feat(voice): OpenAI Whisper API fallback STT`.

### Task 4: LLM abstraction + Gemini Flash provider

- [ ] **Step 4.1** `src/services/intent/types.py` — `ParsedIntent` dataclass (`tool_name: str | None`, `args: dict`, `confidence: float | None`, `raw_text: str`).
- [ ] **Step 4.2** `src/services/intent/llm.py` — `LLMProvider` Protocol с `async parse_intent(text, *, tools, system, now_local) -> ParsedIntent` и dispatcher.
- [ ] **Step 4.3** `src/services/intent/prompt.py` — system-prompt:
   - роль («ты парсер команд для бота-планировщика»)
   - правила интерпретации дат («завтра» = `now_local.date() + 1`, «в полтретьего» = `14:30`, и т.п.)
   - инструкция: вернуть tool-call ИЛИ ничего если команда не подходит
   - jsonable формат now_local передаётся как контекст в каждом вызове
- [ ] **Step 4.4** `src/services/intent/llm_gemini.py` — обёртка над `google.genai`. Tools-описание формируется из `registry.tool_specs()`. Возвращает `ParsedIntent`. Если LLM вернул пустой text без tool-call → `tool_name=None`.
- [ ] **Step 4.5** Тесты: мок Gemini SDK, проверить что для «запиши Иру на завтра 14:30» возвращается правильный tool_name + args; для «привет» — `tool_name=None`.
- [ ] **Step 4.6** ruff/mypy/pytest. Commit: `feat(intent): Gemini Flash LLM provider`.

### Task 5: LLM fallback — OpenAI gpt-4o-mini

- [ ] **Step 5.1** `src/services/intent/llm_openai.py` — обёртка над `openai.chat.completions.create` с function-calling (`tools=...`, `tool_choice="auto"`).
- [ ] **Step 5.2** Тесты с моком SDK.
- [ ] **Step 5.3** ruff/mypy/pytest. Commit: `feat(intent): OpenAI gpt-4o-mini LLM fallback`.

### Task 6: Action registry + Action protocol

- [ ] **Step 6.1** `src/services/intent/types.py` — `Action` Protocol, `ActionContext`, `ActionResponse`, `ActionResult` enum.
- [ ] **Step 6.2** `src/services/intent/registry.py` — `ActionRegistry` с методами `register(action)`, `get(name)`, `tool_specs()` (генерит из `params_schema` каждого action массив для LLM).
- [ ] **Step 6.3** Тест: зарегистрировать dummy-action, проверить `tool_specs()` структуру и `get("name")` lookup.
- [ ] **Step 6.4** ruff/mypy/pytest. Commit: `feat(intent): action registry + protocol`.

### Task 7: Resolvers (client/appointment lookup)

- [ ] **Step 7.1** `src/services/intent/resolvers.py`:
   - `resolve_client(session, name) -> list[Client]` — case-insensitive substring match по `clients.name`.
   - `resolve_appointment(session, *, client_id, date_hint, time_hint, status="scheduled") -> list[Appointment]` — фильтрация записей клиента по опциональным дате/времени.
- [ ] **Step 7.2** Тесты (по 3–4 кейса на каждую функцию).
- [ ] **Step 7.3** ruff/mypy/pytest. Commit: `feat(intent): client/appointment resolvers for actions`.

### Task 8: Action `create_appointment`

- [ ] **Step 8.1** `actions/create_appointment.py`: schema `{client_name, date (YYYY-MM-DD), time (HH:MM), note?, instagram?}`. Required: `client_name`, `date`. `time` — required, но если LLM не разобрал → action возвращает CLARIFY с time-picker'ом.
- [ ] **Step 8.2** `plan`: resolve_client → если 0 → CLARIFY (создать нового клиента?), если >1 → CLARIFY (выбор кнопками), если 1 → собрать confirm-card «Записать <Имя> на <дата> в <время>?», вернуть CONFIRM с pending_payload.
- [ ] **Step 8.3** `execute`: создать запись через `AppointmentRepository`, вызвать `reschedule_for_appointment`, вернуть EXECUTED с «✅ Сохранено».
- [ ] **Step 8.4** Тесты: happy-path; missing time → CLARIFY; 2 клиентки → CLARIFY; new client → CLARIFY (создать?); past date → FAIL.
- [ ] **Step 8.5** ruff/mypy/pytest. Commit: `feat(intent): create_appointment action`.

### Task 9: Action `list_appointments` (read-only)

- [ ] **Step 9.1** Schema `{period: today|tomorrow|week|month|all|date, date?: YYYY-MM-DD}`.
- [ ] **Step 9.2** `plan`: вычислить диапазон, вызвать тот же helper что и кнопка `📋 Записи` → вернуть EXECUTED со списком (текст + клавиатура карточек). Никакого confirm.
- [ ] **Step 9.3** Тесты на 5 значений `period`.
- [ ] **Step 9.4** ruff/mypy/pytest. Commit: `feat(intent): list_appointments action`.

### Task 10: Action `move_appointment`

- [ ] **Step 10.1** Schema `{client_name, current_date?, current_time?, new_date?, new_time?}`. У всех полей кроме `client_name` есть default-стратегия: если current_* не указаны — берём ближайшую запись клиента.
- [ ] **Step 10.2** `plan`: resolve_client → resolve_appointment → если 0 → FAIL «не нашёл записи», >1 → CLARIFY, 1 + new_date+new_time заданы → CONFIRM «Перенести с <старо> на <ново>?»; если new_* не полностью заданы → CLARIFY (date/time picker).
- [ ] **Step 10.3** `execute`: те же шаги что в `appointment_card.on_move_time_picked` — overlap check, reschedule в БД, reschedule notifications.
- [ ] **Step 10.4** Тесты: happy, ambiguous, missing fields, overlap.
- [ ] **Step 10.5** ruff/mypy/pytest. Commit: `feat(intent): move_appointment action`.

### Task 11: Action `cancel_appointment`

- [ ] **Step 11.1** Schema `{client_name, date?, time?}`. По умолчанию — ближайшая запись клиента.
- [ ] **Step 11.2** `plan`: resolve → CONFIRM «Отменить запись <Имя> <дата> <время>?».
- [ ] **Step 11.3** `execute`: сменить status='cancelled', вызвать `cancel_for_appointment` для notifications.
- [ ] **Step 11.4** Тесты.
- [ ] **Step 11.5** Commit: `feat(intent): cancel_appointment action`.

### Task 12: Action `edit_note`

- [ ] **Step 12.1** Schema `{client_name, date?, time?, note}`.
- [ ] **Step 12.2** `plan`: resolve → CONFIRM «Записать заметку «<note>» к записи <Имя> <дата>?».
- [ ] **Step 12.3** `execute`: обновить `appointments.note`.
- [ ] **Step 12.4** Тесты.
- [ ] **Step 12.5** Commit: `feat(intent): edit_note action`.

### Task 13: Action `list_client_history` (read-only)

- [ ] **Step 13.1** Schema `{client_name}`.
- [ ] **Step 13.2** `plan`: resolve → если 0 → FAIL, >1 → CLARIFY, 1 → EXECUTED с тем же экраном что в `clients.py` history.
- [ ] **Step 13.3** Тесты.
- [ ] **Step 13.4** Commit: `feat(intent): list_client_history action`.

### Task 14: Action `delete_client`

- [ ] **Step 14.1** Schema `{client_name}`.
- [ ] **Step 14.2** `plan`: resolve → CONFIRM с предупреждением «Удалить <Имя> и все его записи? Будет сохранено в истории как cancelled.». Двойное подтверждение через ещё одну кнопку «Точно удалить» (как в текущем UI).
- [ ] **Step 14.3** `execute`: cascade delete через `ClientRepository`.
- [ ] **Step 14.4** Тесты.
- [ ] **Step 14.5** Commit: `feat(intent): delete_client action`.

### Task 15: Confirm-card UI primitive

- [ ] **Step 15.1** `src/bot/keyboards/confirm_card.py`: `confirm_card_kb(tag)` — 3 кнопки `[✅ Сохранить] [✏️ Изменить] [❌ Отменить]` с `IntakeCD(action="confirm"|"edit"|"cancel", tag=tag)`. Tag — короткий идентификатор pending action в FSM (uuid4 short).
- [ ] **Step 15.2** Расширить `callback_data.py` (`IntakeCD`).
- [ ] **Step 15.3** Тесты на сериализацию `IntakeCD`.
- [ ] **Step 15.4** Commit: `feat(bot): confirm-card UI primitive`.

### Task 16: Intake handler

- [ ] **Step 16.1** `src/bot/handlers/intake.py`:
   - `@router.message(F.voice)` — load voice file, проверить duration, STT, → парсинг.
   - `@router.message(F.text & ~F.text.startswith("/"))` — парсинг свободного текста (игнорируем команды бота и reply-text-кнопки `+ Запись`/`📋 Записи`/`👥 Клиенты`/`⚙️ Настройки`).
   - Если есть активный FSM (state != None и state.startswith одной из wizard-групп) → `finalize` с «❌ Отменено» перед стартом intake.
- [ ] **Step 16.2** Парсинг flow:
   1. вызов LLM → `ParsedIntent`
   2. если `tool_name is None` → отправить «не понял» + intake_help_kb
   3. action = registry.get(tool_name); вызвать `action.plan(ctx, args)`
   4. на основании `ActionResult`:
      - EXECUTED → отправить text + keyboard
      - CONFIRM → сохранить `pending_payload` в FSM (state=`IntakePending.confirming`, data={tag, action_name, payload}), отправить confirm-card
      - CLARIFY → state=`IntakePending.clarifying`, отправить вопрос с кнопками
      - FAIL → отправить text
- [ ] **Step 16.3** Confirm-card callbacks:
   - `IntakeCD action=confirm` → достать payload из FSM, вызвать `action.execute(ctx, payload)`, отправить результат, finalize.
   - `IntakeCD action=cancel` → finalize с «❌ Отменено».
   - `IntakeCD action=edit` → handoff в соответствующий FSM (для `create` → AddAppointment.confirming с предзаполненными полями).
- [ ] **Step 16.4** Тесты с моками всего стека.
- [ ] **Step 16.5** ruff/mypy/pytest. Commit: `feat(bot): voice/text intake handler + confirm-card flow`.

### Task 17: Disambiguation flow

- [ ] **Step 17.1** Когда action возвращает CLARIFY с вариантами клиентов/записей — рендерим InlineKeyboardMarkup с одной кнопкой на вариант. Callback несёт `IntakeCD(action="clarify", tag=...)`, а в FSM data — список pending choices с тем что выбрать.
- [ ] **Step 17.2** Handler `IntakeCD action=clarify`: достать выбор, дополнить args, вызвать action.plan ещё раз — теперь без двусмысленности.
- [ ] **Step 17.3** Тесты на ambiguous client + ambiguous appointment.
- [ ] **Step 17.4** Commit: `feat(bot): disambiguation flow for intake`.

### Task 18: Failure modes + UX polish

- [ ] **Step 18.1** Voice длиннее `VOICE_MAX_DURATION_SEC` → «Слишком длинное сообщение, до 60 сек».
- [ ] **Step 18.2** STT вернул пустую строку → «Не услышал ничего, попробуй ещё раз».
- [ ] **Step 18.3** LLM упал (timeout/quota) → «Не могу разобрать команду, попробуй кнопками».
- [ ] **Step 18.4** Дата в прошлом → action возвращает FAIL «Дата уже прошла».
- [ ] **Step 18.5** intake_help_kb (после «не понял») — короткий список «Можешь сказать: запиши Иру на завтра 14:30 / покажи записи на сегодня / отмени запись Иры завтра».
- [ ] **Step 18.6** Тесты на каждый failure path.
- [ ] **Step 18.7** Commit: `feat(bot): intake failure modes + help-card`.

### Task 19: Docker smoke

- [ ] **Step 19.1** Перезапустить контейнер. Проверить что faster-whisper модель скачивается (один раз) и грузится в память.
- [ ] **Step 19.2** Голосовое «запиши тестового клиента на завтра в десять» → confirm-card → ✅ → запись создана.
- [ ] **Step 19.3** Текстовое «покажи записи на сегодня» → открывается экран как от кнопки 📋.
- [ ] **Step 19.4** Голосовое «перенеси запись на одиннадцать» (с активным FSM) → FSM отменяется, парсер срабатывает.
- [ ] **Step 19.5** «привет» (no-tool-call) → не понял + help.

### Task 20: Final review + merge

- [ ] **Step 20.1** Запустить ultrareview на `plan/voice-intake` (если доступно), иначе спец-агент adversarial-review.
- [ ] **Step 20.2** Все 189+ тестов зелёные, ruff/mypy clean.
- [ ] **Step 20.3** Fast-forward в master, push в origin. Закрыть Plan #4.
- [ ] **Step 20.4** Обновить `CLAUDE.md` (добавить заметку про intake handler в архитектуру).

---

## Open questions (решаются в процессе)

1. **Handoff на «Изменить»**: какая именно State.* в AddAppointment FSM использовать как точку входа? Самый чистый путь — `AddAppointment.confirming` с предзаполненной FSM data, и оттуда юзер может тапнуть «Изменить» в самом FSM, чтобы пройти все шаги. Уточнить в Task 16.
2. **Кэширование faster-whisper**: модель грузить один раз при старте бота или лениво при первом запросе? Загрузка `small` ~3 сек, RAM 0.5 ГБ — лучше на старте, чтобы первый user-request не ждал.
3. **Gemini rate limit**: 15 RPM — для одного юзера запас огромный. Если когда-нибудь упрёмся — добавить retry с backoff.
4. **Тестирование faster-whisper в CI**: реальный аудио-фикстур vs мок. Мок проще, реальный надёжнее. Решим по ходу — вероятно мок + один integration-тест помеченный `slow`.
5. **Голос на казахском** — спецификация говорит про русский. Если когда-то понадобится двуязычность — можно расширить, в Whisper и Gemini это поддерживается, но MVP только русский.

---

## Testing plan (high-level)

- **Unit**: каждый action — 4–6 тестов (happy + edge cases). Resolvers — 3–4. STT/LLM провайдеры — с моками SDK.
- **Integration**: `tests/bot/handlers/test_intake.py` — полный цикл от `Message` до `bot.send_message` со всеми моками.
- **Smoke (manual)**: Task 19.

---

## Estimated scope

20 задач × ~30–60 мин каждая ≈ 10–20 часов работы (subagent-driven через несколько сессий). По размеру сравнимо с Plan #3 (~16 задач) с поправкой на бóльшую новизну (LLM/STT инфраструктура).

---

## Backwards-compat / migration

- Существующий `services/parser/text_parser.py` оставляем как есть. Он использовался в `text_add` handler для строгого формата `/add YYYY-MM-DD HH:MM Имя`. После Plan #4 этот путь дублируется (LLM-парсер тоже это понимает), но удалять не будем — вдруг юзер привык к строгому формату. Через несколько недель посмотрим использование и решим.
- Никаких миграций БД. Никаких изменений в существующих handler'ах кроме `intake.py` (новый) и одной правки в `system.py` если решим спрятать FSM-cancel хелпер.
