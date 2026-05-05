# Booking Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поверх Foundation поднять полноценный CRUD записей в боте: создание через FSM-форму, через текстовую команду `/add`, списки `/today`/`/tomorrow`/`/week`, карточка клиента с историей за выбранный период, карточка записи (перенос/отмена/заметка). Никаких уведомлений (Plan #3) и голоса (Plan #4) — только presentation поверх готового storage.

**Architecture context:** Foundation готов — все 5 моделей, репозитории (`AppointmentRepository.find_overlap/list_in_range/reschedule`, `ClientRepository.search_by_name/list_recent/update`), `WhitelistMiddleware`, `main_menu_kb()` (с кнопками `+ Запись`, `📅 Сегодня`, `📆 Завтра`, `🗓 Неделя`, `👥 Клиенты`, `⚙️ Настройки`), Redis FSM storage. Booking core добавляет ВТОРОЙ слой — `bot/handlers/`, `bot/keyboards/`, `bot/states.py`, `bot/callback_data.py`, `bot/ui.py`, плюс один сервис-парсер `services/parser/text_parser.py`. Storage не правим.

**Tech Stack (что задействуется):** aiogram 3 (Router, FSMContext, CallbackData factories, inline-keyboards), pydantic для CallbackData, существующий `AppointmentRepository`/`ClientRepository`, `zoneinfo` для timezone-aware дат, `re` для text_parser. Никаких новых зависимостей.

**Shell:** все команды в bash (zsh на macOS). Платформа разработки — Mac, прод через Docker (Python 3.12). Минимальный локальный Python — 3.10.

**Prerequisites:**
- Foundation milestone смержен в `master` (15 коммитов на ветке `plan/foundation`).
- 39 тестов зелёные (`poetry run pytest -v`).
- `poetry run ruff check src tests` clean, `poetry run mypy src` clean.
- Граф собран и хук graphify установлен (см. CLAUDE.md «Knowledge Graph (graphify)»).
- Спека на месте: `~/.claude/plans/swirling-whistling-tulip.md`.

**Decisions, согласованные при написании плана** (закрывают open items спеки):

1. **Формат строки в списках** (`/today`, `/tomorrow`, `/week`, история клиента): `14:00 · Олег · маникюр` — плотно, разделитель `·`, без emoji в строке. Если `visit_note` отсутствует — последний сегмент опускается.
2. **История клиента** открывается через выбор периода (`PeriodPickerCD`): кнопки `[Сегодня] [Неделя] [Месяц] [Все] [📅 Дата]`. После выбора — список того же формата с группировкой по дням, сверху указан выбранный период. `/week` использует тот же компонент с пресетом «7 дней вперёд от сегодня».
3. **Длительность визита**: дефолт 60 мин из `settings.default_duration_min`, в UI создания записи **не показывается**. Используется только для `find_overlap`.
4. **Recovery FSM на старте, восстановление прерванного flow** — НЕ в этом плане (Plan #5 — финальный полишинг UX). Здесь только базовая дисциплина (`/cancel`, idle TTL Redis, finalize on success).

---

## File Structure

Новые файлы:

| Путь | Назначение |
|---|---|
| `src/bot/callback_data.py` | Типизированные `ApptCD`, `ClientCD`, `CalendarCD`, `TimeCD`, `PeriodCD`, `WizardCD` (`v=1`) |
| `src/bot/states.py` | `AddAppointment`, `EditClient`, `HistoryFilter`, `EditAppointment` |
| `src/bot/ui.py` | Хелперы `advance`, `finalize`, `cancel`, `safe_edit` |
| `src/bot/middlewares/concurrency.py` | In-memory lock по `(chat_id, message_id)` для CallbackQuery |
| `src/bot/keyboards/calendar.py` | Inline-календарь на месяц со стрелками |
| `src/bot/keyboards/time_picker.py` | Сетка 09:00–20:30 шагом 30 мин + «Другое время» |
| `src/bot/keyboards/period_picker.py` | `[Сегодня][Неделя][Месяц][Все][📅 Дата]` |
| `src/bot/keyboards/client_picker.py` | Последние клиенты + 🔍 Поиск + ➕ Новый |
| `src/bot/keyboards/confirm.py` | `[✅ Сохранить][✏️ Поправить][❌ Отмена]` для карточки |
| `src/bot/keyboards/appointment_card.py` | `[Перенести][Заметка][Отменить][Закрыть]` |
| `src/bot/handlers/add_appointment.py` | FSM-flow создания записи (Поток B спеки) |
| `src/bot/handlers/text_add.py` | `/add YYYY-MM-DD HH:MM Имя [@insta] [заметка]` |
| `src/bot/handlers/lists.py` | `/today`, `/tomorrow`, `/week` + reply-keyboard кнопки |
| `src/bot/handlers/clients.py` | `/clients` + карточка + история с period-picker |
| `src/bot/handlers/appointment_card.py` | Карточка записи с действиями |
| `src/bot/handlers/system.py` | `/cancel`, `/help`, global error-handler |
| `src/services/parser/text_parser.py` | Regex-парсер строки `/add` |
| `src/services/formatters.py` | `format_appointment_line`, `format_period_header`, `group_by_day` |
| `tests/bot/test_callback_data.py` | Сериализация/десериализация всех CD |
| `tests/bot/test_ui.py` | Хелперы advance/finalize/cancel |
| `tests/bot/test_concurrency_middleware.py` | Двойной тап игнорируется |
| `tests/bot/test_keyboards.py` | _Modify_ — добавить тесты для всех новых клавиатур |
| `tests/bot/test_add_appointment_flow.py` | FSM happy path + конфликт + cancel |
| `tests/bot/test_text_add_handler.py` | `/add` regex-парсинг + конфликт |
| `tests/bot/test_lists_handler.py` | `/today` пустой/непустой, `/week` группировка |
| `tests/bot/test_clients_handler.py` | `/clients` + период-пикер + история |
| `tests/bot/test_appointment_card.py` | Перенос, отмена, заметка |
| `tests/bot/test_system_handler.py` | `/cancel` чистит state, `/help` отвечает |
| `tests/services/test_text_parser.py` | Все ветки regex |
| `tests/services/test_formatters.py` | Edge-cases форматирования |

Modify:
- `src/main.py` — `_build_dispatcher` регистрирует новые routers + `ConcurrencyMiddleware`.

**Принцип:** один файл = одна ответственность. Никаких god-handler'ов. Каждая клавиатура отдельным модулем — потом легко добавлять варианты в Plan #3/#4.

---

## Tasks

### Task 1: Branch and CallbackData factories

**Files:**
- Create: `src/bot/callback_data.py`
- Create: `tests/bot/test_callback_data.py`

- [ ] **Step 1.1: Create branch**
  ```bash
  git switch -c plan/booking-core
  ```

- [ ] **Step 1.2: Write failing tests** in `tests/bot/test_callback_data.py`:
  ```python
  """Tests for CallbackData factories — round-trip serialization."""
  from __future__ import annotations
  import pytest
  from src.bot.callback_data import ApptCD, CalendarCD, ClientCD, PeriodCD, TimeCD, WizardCD


  class TestApptCD:
      def test_round_trip_view(self) -> None:
          cd = ApptCD(action="view", appointment_id=42)
          packed = cd.pack()
          unpacked = ApptCD.unpack(packed)
          assert unpacked == cd

      def test_v_defaults_to_1(self) -> None:
          assert ApptCD(action="view", appointment_id=1).v == 1


  class TestClientCD:
      @pytest.mark.parametrize("action", ["pick", "view", "edit", "history", "new"])
      def test_round_trip(self, action: str) -> None:
          cd = ClientCD(action=action, client_id=7)  # type: ignore[arg-type]
          assert ClientCD.unpack(cd.pack()) == cd


  class TestCalendarCD:
      def test_pick_carries_iso_date(self) -> None:
          cd = CalendarCD(action="pick", iso_date="2026-05-06")
          assert CalendarCD.unpack(cd.pack()).iso_date == "2026-05-06"

      def test_nav_carries_direction(self) -> None:
          cd = CalendarCD(action="nav", nav="next", iso_date="2026-05-01")
          assert CalendarCD.unpack(cd.pack()).nav == "next"


  class TestTimeCD:
      def test_round_trip_hhmm(self) -> None:
          cd = TimeCD(hhmm="14:30")
          assert TimeCD.unpack(cd.pack()).hhmm == "14:30"

      def test_custom_marker(self) -> None:
          cd = TimeCD(hhmm="custom")
          assert TimeCD.unpack(cd.pack()).hhmm == "custom"


  class TestPeriodCD:
      @pytest.mark.parametrize("kind", ["today", "week", "month", "all", "date"])
      def test_round_trip(self, kind: str) -> None:
          cd = PeriodCD(kind=kind, scope="client", scope_id=3)  # type: ignore[arg-type]
          assert PeriodCD.unpack(cd.pack()) == cd


  class TestWizardCD:
      def test_action_only(self) -> None:
          cd = WizardCD(action="cancel")
          assert WizardCD.unpack(cd.pack()).action == "cancel"
  ```

  ```bash
  poetry run pytest tests/bot/test_callback_data.py -v
  # Expected: ImportError — модуль ещё не создан.
  ```

- [ ] **Step 1.3: Implement** `src/bot/callback_data.py`:
  ```python
  """Typed CallbackData factories with version field for forward-compat.

  Все callback'и используют префиксы и `v=1` — при изменении схемы повышаем v
  и фильтр режет старые callback'и с alert'ом «сообщение устарело».
  """
  from __future__ import annotations
  from typing import Literal
  from aiogram.filters.callback_data import CallbackData


  class ApptCD(CallbackData, prefix="appt", sep="|"):
      v: int = 1
      action: Literal["view", "move", "cancel", "note", "client", "close"]
      appointment_id: int


  class ClientCD(CallbackData, prefix="client", sep="|"):
      v: int = 1
      action: Literal["pick", "view", "edit", "history", "new"]
      client_id: int = 0


  class CalendarCD(CallbackData, prefix="cal", sep="|"):
      v: int = 1
      action: Literal["pick", "nav", "noop"]
      iso_date: str = ""        # YYYY-MM-DD anchor for the visible month
      nav: str = ""             # "prev" | "next" | ""


  class TimeCD(CallbackData, prefix="time", sep="|"):
      v: int = 1
      hhmm: str                 # "HH:MM" or literal "custom"


  class PeriodCD(CallbackData, prefix="period", sep="|"):
      v: int = 1
      kind: Literal["today", "tomorrow", "week", "month", "all", "date"]
      scope: Literal["lists", "client"] = "lists"
      scope_id: int = 0         # client_id when scope="client"


  class WizardCD(CallbackData, prefix="wiz", sep="|"):
      v: int = 1
      action: Literal["save", "edit", "cancel", "skip", "back"]
  ```

- [ ] **Step 1.4: Run tests + lint**
  ```bash
  poetry run pytest tests/bot/test_callback_data.py -v
  poetry run ruff check src tests
  poetry run mypy src
  ```

- [ ] **Step 1.5: Commit**
  ```bash
  git add src/bot/callback_data.py tests/bot/test_callback_data.py
  git commit -m "feat(bot): typed CallbackData factories for booking core"
  ```

---

### Task 2: FSM states

**Files:**
- Create: `src/bot/states.py`
- Create: `tests/bot/test_states.py`

- [ ] **Step 2.1: Failing test** in `tests/bot/test_states.py`:
  ```python
  """States are just StatesGroup containers — verify they exist with right names."""
  from src.bot.states import AddAppointment, EditAppointment, EditClient, HistoryFilter


  def test_add_appointment_states() -> None:
      assert AddAppointment.choosing_client.state == "AddAppointment:choosing_client"
      assert AddAppointment.searching_client.state == "AddAppointment:searching_client"
      assert AddAppointment.creating_client_name.state == "AddAppointment:creating_client_name"
      assert AddAppointment.creating_client_instagram.state == "AddAppointment:creating_client_instagram"
      assert AddAppointment.choosing_date.state == "AddAppointment:choosing_date"
      assert AddAppointment.entering_date.state == "AddAppointment:entering_date"
      assert AddAppointment.choosing_time.state == "AddAppointment:choosing_time"
      assert AddAppointment.entering_time.state == "AddAppointment:entering_time"
      assert AddAppointment.entering_note.state == "AddAppointment:entering_note"
      assert AddAppointment.confirming.state == "AddAppointment:confirming"


  def test_other_groups_exist() -> None:
      assert EditAppointment.entering_note.state == "EditAppointment:entering_note"
      assert EditClient.editing_name.state == "EditClient:editing_name"
      assert HistoryFilter.entering_date.state == "HistoryFilter:entering_date"
  ```

- [ ] **Step 2.2: Implement** `src/bot/states.py`:
  ```python
  """FSM state groups for multi-step flows."""
  from __future__ import annotations
  from aiogram.fsm.state import State, StatesGroup


  class AddAppointment(StatesGroup):
      choosing_client = State()
      searching_client = State()
      creating_client_name = State()
      creating_client_instagram = State()
      choosing_date = State()
      entering_date = State()
      choosing_time = State()
      entering_time = State()
      entering_note = State()
      confirming = State()


  class EditAppointment(StatesGroup):
      entering_note = State()
      choosing_new_date = State()
      choosing_new_time = State()


  class EditClient(StatesGroup):
      editing_name = State()
      editing_instagram = State()
      editing_notes = State()


  class HistoryFilter(StatesGroup):
      entering_date = State()
  ```

- [ ] **Step 2.3: Run + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_states.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/states.py tests/bot/test_states.py
  git commit -m "feat(bot): FSM state groups for AddAppointment + edits"
  ```

---

### Task 3: UI helpers

**Files:**
- Create: `src/bot/ui.py`
- Create: `tests/bot/test_ui.py`

Дисциплина «одно активное FSM-сообщение» (см. спеку §FSM): в state хранится
`flow_message_id`. На каждом шаге редактируем именно его. Хелперы:
- `advance(bot, chat_id, state, text, kb)` — редактируем `flow_message_id` или шлём новое если первого шага ещё не было; обновляем state.
- `finalize(bot, chat_id, state, text)` — редактируем без клавиатуры, очищаем state.
- `cancel(bot, chat_id, state)` — финализирует с «❌ Отменено».

- [ ] **Step 3.1: Failing tests** in `tests/bot/test_ui.py`:
  ```python
  """ui helpers — edit existing message OR send new, then chain."""
  from __future__ import annotations
  from unittest.mock import AsyncMock, MagicMock

  import pytest
  from aiogram.fsm.context import FSMContext
  from aiogram.fsm.storage.memory import MemoryStorage
  from aiogram.fsm.storage.base import StorageKey

  from src.bot.ui import advance, cancel, finalize


  @pytest.fixture
  async def state() -> FSMContext:
      storage = MemoryStorage()
      key = StorageKey(bot_id=1, chat_id=100, user_id=100)
      return FSMContext(storage=storage, key=key)


  @pytest.fixture
  def bot() -> MagicMock:
      b = MagicMock()
      b.send_message = AsyncMock(return_value=MagicMock(message_id=555))
      b.edit_message_text = AsyncMock()
      return b


  async def test_advance_sends_first_message_and_stores_id(bot: MagicMock, state: FSMContext) -> None:
      await advance(bot, chat_id=100, state=state, text="step 1", reply_markup=None)
      bot.send_message.assert_awaited_once()
      data = await state.get_data()
      assert data["flow_message_id"] == 555


  async def test_advance_edits_existing_flow_message(bot: MagicMock, state: FSMContext) -> None:
      await state.update_data(flow_message_id=999)
      await advance(bot, chat_id=100, state=state, text="step 2", reply_markup=None)
      bot.edit_message_text.assert_awaited_once()
      bot.send_message.assert_not_awaited()


  async def test_finalize_strips_keyboard_and_clears_state(bot: MagicMock, state: FSMContext) -> None:
      await state.update_data(flow_message_id=999, draft={"x": 1})
      await finalize(bot, chat_id=100, state=state, text="✅ saved")
      bot.edit_message_text.assert_awaited_once()
      kwargs = bot.edit_message_text.await_args.kwargs
      assert kwargs.get("reply_markup") is None
      assert await state.get_state() is None


  async def test_cancel_sends_cancel_text_and_clears_state(bot: MagicMock, state: FSMContext) -> None:
      await state.update_data(flow_message_id=999)
      await cancel(bot, chat_id=100, state=state)
      bot.edit_message_text.assert_awaited_once()
      assert "Отмен" in bot.edit_message_text.await_args.kwargs["text"]
      assert await state.get_state() is None
  ```

- [ ] **Step 3.2: Implement** `src/bot/ui.py`:
  ```python
  """Single active FSM message helpers — edit-in-place vs send-new."""
  from __future__ import annotations
  import logging
  from aiogram import Bot
  from aiogram.exceptions import TelegramBadRequest
  from aiogram.fsm.context import FSMContext
  from aiogram.types import InlineKeyboardMarkup

  log = logging.getLogger(__name__)
  CANCELLED_TEXT = "❌ Отменено"


  async def advance(
      bot: Bot,
      *,
      chat_id: int,
      state: FSMContext,
      text: str,
      reply_markup: InlineKeyboardMarkup | None,
  ) -> None:
      """Edit `flow_message_id` if present, else send a new message and store its id."""
      data = await state.get_data()
      flow_id = data.get("flow_message_id")
      if flow_id is None:
          msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
          await state.update_data(flow_message_id=msg.message_id)
          return
      try:
          await bot.edit_message_text(
              chat_id=chat_id, message_id=flow_id, text=text, reply_markup=reply_markup,
          )
      except TelegramBadRequest as exc:
          if "message is not modified" in str(exc).lower():
              return
          log.warning("flow message edit failed (%s); sending new", exc)
          msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
          await state.update_data(flow_message_id=msg.message_id)


  async def finalize(bot: Bot, *, chat_id: int, state: FSMContext, text: str) -> None:
      """Replace flow message with final text, drop the keyboard, clear state."""
      data = await state.get_data()
      flow_id = data.get("flow_message_id")
      if flow_id is not None:
          try:
              await bot.edit_message_text(
                  chat_id=chat_id, message_id=flow_id, text=text, reply_markup=None,
              )
          except TelegramBadRequest as exc:
              log.warning("finalize edit failed (%s); sending plain", exc)
              await bot.send_message(chat_id=chat_id, text=text)
      else:
          await bot.send_message(chat_id=chat_id, text=text)
      await state.clear()


  async def cancel(bot: Bot, *, chat_id: int, state: FSMContext) -> None:
      """Cancel current flow with a fixed `❌ Отменено` line."""
      await finalize(bot, chat_id=chat_id, state=state, text=CANCELLED_TEXT)
  ```

- [ ] **Step 3.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_ui.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/ui.py tests/bot/test_ui.py
  git commit -m "feat(bot): FSM ui helpers (advance/finalize/cancel)"
  ```

---

### Task 4: ConcurrencyMiddleware

**Files:**
- Create: `src/bot/middlewares/concurrency.py`
- Create: `tests/bot/test_concurrency_middleware.py`

In-memory lock по `(chat_id, message_id)` для CallbackQuery. Двойной тап на
кнопке (например «Сохранить» в карточке-подтверждении) — второй вызов сразу
отвечает `answer_callback_query()` и не вызывает handler.

- [ ] **Step 4.1: Failing tests** in `tests/bot/test_concurrency_middleware.py`:
  ```python
  """ConcurrencyMiddleware drops second click on the same (chat_id, message_id)."""
  from __future__ import annotations
  import asyncio
  from unittest.mock import AsyncMock, MagicMock
  from src.bot.middlewares.concurrency import ConcurrencyMiddleware


  def _make_callback(chat_id: int, message_id: int) -> MagicMock:
      cb = MagicMock()
      cb.message = MagicMock(chat=MagicMock(id=chat_id), message_id=message_id)
      cb.answer = AsyncMock()
      return cb


  async def test_first_click_passes_through() -> None:
      mw = ConcurrencyMiddleware()
      handler = AsyncMock(return_value="ok")
      cb = _make_callback(1, 100)
      result = await mw(handler, cb, {})
      assert result == "ok"
      handler.assert_awaited_once()


  async def test_second_click_during_handler_is_dropped() -> None:
      mw = ConcurrencyMiddleware()

      async def slow_handler(_event, _data):  # type: ignore[no-untyped-def]
          await asyncio.sleep(0.05)
          return "done"

      cb1 = _make_callback(1, 100)
      cb2 = _make_callback(1, 100)
      task1 = asyncio.create_task(mw(slow_handler, cb1, {}))
      await asyncio.sleep(0.01)
      result2 = await mw(slow_handler, cb2, {})
      result1 = await task1
      assert result1 == "done"
      assert result2 is None
      cb2.answer.assert_awaited_once()


  async def test_different_messages_do_not_block() -> None:
      mw = ConcurrencyMiddleware()
      handler = AsyncMock(return_value="ok")
      r1 = await mw(handler, _make_callback(1, 100), {})
      r2 = await mw(handler, _make_callback(1, 101), {})
      assert r1 == "ok" and r2 == "ok"
      assert handler.await_count == 2
  ```

- [ ] **Step 4.2: Implement** `src/bot/middlewares/concurrency.py`:
  ```python
  """In-memory lock per (chat_id, message_id) for CallbackQuery double-tap protection."""
  from __future__ import annotations
  import asyncio
  from collections.abc import Awaitable, Callable
  from typing import Any
  from aiogram import BaseMiddleware
  from aiogram.types import CallbackQuery, TelegramObject


  class ConcurrencyMiddleware(BaseMiddleware):
      def __init__(self) -> None:
          super().__init__()
          self._busy: set[tuple[int, int]] = set()
          self._lock = asyncio.Lock()

      async def __call__(
          self,
          handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
          event: TelegramObject,
          data: dict[str, Any],
      ) -> Any:
          if not isinstance(event, CallbackQuery) or event.message is None:
              return await handler(event, data)
          key = (event.message.chat.id, event.message.message_id)
          async with self._lock:
              if key in self._busy:
                  await event.answer()
                  return None
              self._busy.add(key)
          try:
              return await handler(event, data)
          finally:
              async with self._lock:
                  self._busy.discard(key)
  ```

- [ ] **Step 4.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_concurrency_middleware.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/middlewares/concurrency.py tests/bot/test_concurrency_middleware.py
  git commit -m "feat(bot): ConcurrencyMiddleware drops double-tap on same message"
  ```

---

### Task 5: text_parser for `/add` command

**Files:**
- Create: `src/services/parser/text_parser.py`
- Create: `tests/services/test_text_parser.py`

Жёсткий regex для строки `/add YYYY-MM-DD HH:MM Имя [@instagram] [заметка]`.
LLM fallback (Plan #4) подключим позже — здесь только regex.

- [ ] **Step 5.1: Failing tests** in `tests/services/test_text_parser.py`:
  ```python
  """text_parser — regex for /add command."""
  from __future__ import annotations
  from datetime import datetime
  import pytest
  from src.services.parser.text_parser import ParseError, parse_add_command


  class TestParseAddCommand:
      def test_full_form(self) -> None:
          result = parse_add_command("2026-05-06 14:30 Олег @oleg_insta маникюр")
          assert result.starts_at == datetime(2026, 5, 6, 14, 30)
          assert result.client_name == "Олег"
          assert result.instagram == "oleg_insta"
          assert result.visit_note == "маникюр"

      def test_without_instagram(self) -> None:
          result = parse_add_command("2026-05-06 14:30 Олег маникюр")
          assert result.client_name == "Олег"
          assert result.instagram is None
          assert result.visit_note == "маникюр"

      def test_without_note(self) -> None:
          result = parse_add_command("2026-05-06 14:30 Олег @oleg_insta")
          assert result.visit_note is None
          assert result.instagram == "oleg_insta"

      def test_minimal(self) -> None:
          result = parse_add_command("2026-05-06 14:30 Олег")
          assert result.client_name == "Олег"
          assert result.instagram is None
          assert result.visit_note is None

      def test_two_word_name_with_instagram(self) -> None:
          result = parse_add_command("2026-05-06 14:30 Олег Иванов @oleg маникюр")
          assert result.client_name == "Олег Иванов"

      def test_instagram_at_optional(self) -> None:
          result = parse_add_command("2026-05-06 14:30 Олег oleg_insta")
          # без @ — это просто часть имени/заметки, ig=None
          assert result.instagram is None

      @pytest.mark.parametrize("bad", [
          "не команда вообще",
          "2026-05-06 Олег",
          "2026/05/06 14:30 Олег",
          "2026-13-06 14:30 Олег",
          "2026-05-06 25:30 Олег",
          "2026-05-06 14:30",
      ])
      def test_bad_inputs_raise(self, bad: str) -> None:
          with pytest.raises(ParseError):
              parse_add_command(bad)
  ```

- [ ] **Step 5.2: Implement** `src/services/parser/text_parser.py`:
  ```python
  """Regex parser for the textual /add command."""
  from __future__ import annotations
  import re
  from dataclasses import dataclass
  from datetime import datetime


  class ParseError(ValueError):
      """Raised when a string does not match the /add grammar."""


  @dataclass(frozen=True)
  class ParsedAdd:
      starts_at: datetime
      client_name: str
      instagram: str | None
      visit_note: str | None


  _PATTERN = re.compile(
      r"^\s*"
      r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
      r"(?P<time>\d{2}:\d{2})\s+"
      r"(?P<rest>\S.*?)\s*$"
  )


  def parse_add_command(text: str) -> ParsedAdd:
      m = _PATTERN.match(text)
      if not m:
          raise ParseError(f"Cannot parse: {text!r}")
      try:
          starts_at = datetime.strptime(f"{m['date']} {m['time']}", "%Y-%m-%d %H:%M")
      except ValueError as exc:
          raise ParseError(str(exc)) from exc

      rest = m["rest"]
      ig_match = re.search(r"@([A-Za-z0-9._]+)", rest)
      instagram = ig_match.group(1) if ig_match else None

      if instagram:
          rest = (rest[: ig_match.start()] + rest[ig_match.end():]).strip()

      tokens = rest.split(maxsplit=2)
      if not tokens:
          raise ParseError("Client name is required")

      # Heuristic: имя — это первое слово (одно), либо первые два слова если третий
      # токен — заметка (т.е. >2 токенов в rest без instagram).
      if len(tokens) == 1:
          client_name = tokens[0]
          visit_note = None
      elif len(tokens) == 2:
          client_name = tokens[0]
          visit_note = tokens[1]
      else:
          client_name = f"{tokens[0]} {tokens[1]}"
          visit_note = tokens[2]

      return ParsedAdd(
          starts_at=starts_at,
          client_name=client_name,
          instagram=instagram,
          visit_note=visit_note,
      )
  ```

  Заметка по эвристике двух слов имени: тест-кейс `test_two_word_name_with_instagram`
  работает потому что `@oleg` уже отрезан до сплита — остаётся `Олег Иванов маникюр`,
  3 токена → имя = «Олег Иванов», заметка = «маникюр».

- [ ] **Step 5.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/services/test_text_parser.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/services/parser/text_parser.py tests/services/test_text_parser.py
  git commit -m "feat(services): regex text_parser for /add command"
  ```

---

### Task 6: Formatters

**Files:**
- Create: `src/services/formatters.py`
- Create: `tests/services/test_formatters.py`

Помощники форматирования вывода — **единая точка** правил отображения, чтобы
не плодить логику по handler'ам.

- [ ] **Step 6.1: Failing tests** in `tests/services/test_formatters.py`:
  ```python
  from __future__ import annotations
  from datetime import datetime
  from zoneinfo import ZoneInfo

  from src.services.formatters import (
      format_appointment_line, format_period_header, group_by_day, format_date_ru,
  )
  from src.storage.models import Appointment, Client


  TZ = ZoneInfo("Asia/Almaty")


  def _appt(starts_at: datetime, *, client_name: str = "Олег", note: str | None = "маникюр") -> tuple[Appointment, Client]:
      client = Client(id=1, name=client_name, instagram=None, notes=None, created_at=starts_at)
      appt = Appointment(
          id=10, client_id=1, starts_at=starts_at, duration_min=60,
          visit_note=note, status="scheduled", created_at=starts_at,
      )
      return appt, client


  class TestFormatAppointmentLine:
      def test_with_note(self) -> None:
          appt, c = _appt(datetime(2026, 5, 6, 14, 0, tzinfo=TZ))
          assert format_appointment_line(appt, c, tz=TZ) == "14:00 · Олег · маникюр"

      def test_without_note(self) -> None:
          appt, c = _appt(datetime(2026, 5, 6, 14, 0, tzinfo=TZ), note=None)
          assert format_appointment_line(appt, c, tz=TZ) == "14:00 · Олег"

      def test_converts_to_local_tz(self) -> None:
          # appointment в UTC, форматирование в Asia/Almaty (+05:00)
          appt, c = _appt(datetime(2026, 5, 6, 9, 0, tzinfo=ZoneInfo("UTC")))
          assert format_appointment_line(appt, c, tz=TZ).startswith("14:00")


  class TestFormatDateRu:
      def test_basic(self) -> None:
          d = datetime(2026, 5, 6, 0, 0, tzinfo=TZ)  # вторник
          assert format_date_ru(d) == "6 мая (вт)"


  class TestGroupByDay:
      def test_groups_by_local_date(self) -> None:
          a1, c = _appt(datetime(2026, 5, 6, 14, 0, tzinfo=TZ))
          a2, _ = _appt(datetime(2026, 5, 6, 15, 0, tzinfo=TZ), client_name="Аня", note=None)
          a3, _ = _appt(datetime(2026, 5, 7, 10, 0, tzinfo=TZ), client_name="Боря", note="педикюр")
          result = group_by_day([(a1, c), (a2, c), (a3, c)], tz=TZ)
          assert list(result.keys()) == [
              datetime(2026, 5, 6, tzinfo=TZ).date(),
              datetime(2026, 5, 7, tzinfo=TZ).date(),
          ]
          assert len(result[datetime(2026, 5, 6, tzinfo=TZ).date()]) == 2


  class TestFormatPeriodHeader:
      def test_today(self) -> None:
          assert "Сегодня" in format_period_header("today", anchor=datetime(2026, 5, 6, tzinfo=TZ))

      def test_week(self) -> None:
          assert "Неделя" in format_period_header("week", anchor=datetime(2026, 5, 6, tzinfo=TZ))
  ```

- [ ] **Step 6.2: Implement** `src/services/formatters.py`:
  ```python
  """Display formatters — single source of truth for list/card layout."""
  from __future__ import annotations
  from collections import OrderedDict
  from datetime import date, datetime
  from zoneinfo import ZoneInfo

  from src.storage.models import Appointment, Client

  _MONTHS_RU = [
      "", "января", "февраля", "марта", "апреля", "мая", "июня",
      "июля", "августа", "сентября", "октября", "ноября", "декабря",
  ]
  _WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


  def format_appointment_line(appt: Appointment, client: Client, *, tz: ZoneInfo) -> str:
      local = appt.starts_at.astimezone(tz) if appt.starts_at.tzinfo else appt.starts_at
      hhmm = local.strftime("%H:%M")
      if appt.visit_note:
          return f"{hhmm} · {client.name} · {appt.visit_note}"
      return f"{hhmm} · {client.name}"


  def format_date_ru(d: datetime) -> str:
      return f"{d.day} {_MONTHS_RU[d.month]} ({_WEEKDAYS_RU[d.weekday()]})"


  def group_by_day(
      pairs: list[tuple[Appointment, Client]], *, tz: ZoneInfo,
  ) -> "OrderedDict[date, list[tuple[Appointment, Client]]]":
      result: OrderedDict[date, list[tuple[Appointment, Client]]] = OrderedDict()
      for appt, client in pairs:
          local = appt.starts_at.astimezone(tz) if appt.starts_at.tzinfo else appt.starts_at
          result.setdefault(local.date(), []).append((appt, client))
      return result


  def format_period_header(kind: str, *, anchor: datetime) -> str:
      labels = {
          "today": "Сегодня",
          "tomorrow": "Завтра",
          "week": f"Неделя ({format_date_ru(anchor)} → +6 дней)",
          "month": f"Месяц ({_MONTHS_RU[anchor.month].capitalize()} {anchor.year})",
          "all": "Все записи",
          "date": format_date_ru(anchor),
      }
      return labels.get(kind, "Период")
  ```

- [ ] **Step 6.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/services/test_formatters.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/services/formatters.py tests/services/test_formatters.py
  git commit -m "feat(services): formatters for list/card display"
  ```

---

### Task 7: Calendar keyboard

**Files:**
- Create: `src/bot/keyboards/calendar.py`
- Modify: `tests/bot/test_keyboards.py`

Inline-сетка месяца, 7 колонок (пн–вс), стрелки `«` `»` для перехода
между месяцами.

- [ ] **Step 7.1: Failing tests** — добавить в `tests/bot/test_keyboards.py`:
  ```python
  from datetime import date
  from src.bot.keyboards.calendar import calendar_kb


  class TestCalendarKb:
      def test_renders_for_a_month(self) -> None:
          kb = calendar_kb(anchor=date(2026, 5, 1))
          # 1 header (mo title) + 1 weekday row + 5-6 week rows + 1 nav row
          assert len(kb.inline_keyboard) >= 7
          all_buttons = [b for row in kb.inline_keyboard for b in row]
          # Must contain "1" through "31" for May 2026
          texts = {b.text for b in all_buttons}
          assert "1" in texts and "31" in texts

      def test_nav_buttons_present(self) -> None:
          kb = calendar_kb(anchor=date(2026, 5, 1))
          last_row = kb.inline_keyboard[-1]
          texts = [b.text for b in last_row]
          assert "«" in texts and "»" in texts
  ```

- [ ] **Step 7.2: Implement** `src/bot/keyboards/calendar.py`:
  ```python
  """Inline calendar — month grid with nav."""
  from __future__ import annotations
  import calendar as _cal
  from datetime import date

  from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
  from src.bot.callback_data import CalendarCD

  _MONTHS_RU = [
      "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
      "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
  ]
  _WEEKDAY_HEADER = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
  _NOOP = CalendarCD(action="noop").pack()


  def calendar_kb(*, anchor: date) -> InlineKeyboardMarkup:
      year, month = anchor.year, anchor.month
      title = f"{_MONTHS_RU[month]} {year}"
      header = [InlineKeyboardButton(text=title, callback_data=_NOOP)]
      weekdays = [InlineKeyboardButton(text=w, callback_data=_NOOP) for w in _WEEKDAY_HEADER]

      cal = _cal.Calendar(firstweekday=0)
      rows: list[list[InlineKeyboardButton]] = [header, weekdays]
      for week in cal.monthdayscalendar(year, month):
          row: list[InlineKeyboardButton] = []
          for day in week:
              if day == 0:
                  row.append(InlineKeyboardButton(text=" ", callback_data=_NOOP))
              else:
                  iso = f"{year:04d}-{month:02d}-{day:02d}"
                  row.append(InlineKeyboardButton(
                      text=str(day),
                      callback_data=CalendarCD(action="pick", iso_date=iso).pack(),
                  ))
          rows.append(row)

      first = date(year, month, 1).isoformat()
      nav = [
          InlineKeyboardButton(text="«", callback_data=CalendarCD(action="nav", nav="prev", iso_date=first).pack()),
          InlineKeyboardButton(text=" ", callback_data=_NOOP),
          InlineKeyboardButton(text="»", callback_data=CalendarCD(action="nav", nav="next", iso_date=first).pack()),
      ]
      rows.append(nav)
      return InlineKeyboardMarkup(inline_keyboard=rows)
  ```

- [ ] **Step 7.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_keyboards.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/keyboards/calendar.py tests/bot/test_keyboards.py
  git commit -m "feat(bot): inline calendar keyboard with month nav"
  ```

---

### Task 8: Time picker, period picker, client picker, confirm, appointment-card keyboards

**Files:**
- Create: `src/bot/keyboards/time_picker.py`
- Create: `src/bot/keyboards/period_picker.py`
- Create: `src/bot/keyboards/client_picker.py`
- Create: `src/bot/keyboards/confirm.py`
- Create: `src/bot/keyboards/appointment_card.py`
- Modify: `tests/bot/test_keyboards.py`

- [ ] **Step 8.1: Failing tests** — добавить в `tests/bot/test_keyboards.py`:
  ```python
  from src.bot.keyboards.time_picker import time_picker_kb
  from src.bot.keyboards.period_picker import period_picker_kb
  from src.bot.keyboards.client_picker import client_picker_kb
  from src.bot.keyboards.confirm import confirm_kb
  from src.bot.keyboards.appointment_card import appointment_card_kb
  from src.storage.models import Client


  class TestTimePicker:
      def test_grid_includes_business_hours(self) -> None:
          kb = time_picker_kb()
          all_text = {b.text for row in kb.inline_keyboard for b in row}
          assert {"09:00", "12:00", "20:00"}.issubset(all_text)
          assert "Другое время" in all_text


  class TestPeriodPicker:
      def test_lists_scope(self) -> None:
          kb = period_picker_kb(scope="lists")
          texts = {b.text for row in kb.inline_keyboard for b in row}
          assert {"Сегодня", "Неделя", "Месяц", "Все"}.issubset(texts)

      def test_client_scope_includes_id(self) -> None:
          kb = period_picker_kb(scope="client", scope_id=42)
          # Все callback_data должны нести scope_id=42
          for row in kb.inline_keyboard:
              for b in row:
                  if b.callback_data and b.callback_data.startswith("period|"):
                      assert "|42" in b.callback_data or b.callback_data.endswith("|42")


  class TestClientPicker:
      def test_lists_recent_with_search_and_new(self) -> None:
          clients = [
              Client(id=1, name="Олег", created_at=None),
              Client(id=2, name="Аня", created_at=None),
          ]
          kb = client_picker_kb(recent=clients)
          texts = [b.text for row in kb.inline_keyboard for b in row]
          assert "Олег" in texts and "Аня" in texts
          assert "🔍 Поиск" in texts and "➕ Новый клиент" in texts


  class TestConfirmKb:
      def test_three_buttons(self) -> None:
          kb = confirm_kb()
          texts = [b.text for row in kb.inline_keyboard for b in row]
          assert "✅ Сохранить" in texts and "✏️ Поправить" in texts and "❌ Отмена" in texts


  class TestAppointmentCardKb:
      def test_full_actions(self) -> None:
          kb = appointment_card_kb(appointment_id=10)
          texts = [b.text for row in kb.inline_keyboard for b in row]
          assert {"Перенести", "Заметка", "Отменить", "Закрыть"}.issubset(set(texts))
  ```

- [ ] **Step 8.2: Implement** все 5 файлов:

  **`src/bot/keyboards/time_picker.py`:**
  ```python
  """Time grid 09:00–20:30 step 30min + 'Другое время'."""
  from __future__ import annotations
  from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
  from src.bot.callback_data import TimeCD


  def time_picker_kb() -> InlineKeyboardMarkup:
      slots: list[str] = []
      for hh in range(9, 21):
          slots.append(f"{hh:02d}:00")
          slots.append(f"{hh:02d}:30")
      rows: list[list[InlineKeyboardButton]] = []
      for i in range(0, len(slots), 4):
          rows.append([
              InlineKeyboardButton(text=s, callback_data=TimeCD(hhmm=s).pack())
              for s in slots[i : i + 4]
          ])
      rows.append([InlineKeyboardButton(text="Другое время", callback_data=TimeCD(hhmm="custom").pack())])
      return InlineKeyboardMarkup(inline_keyboard=rows)
  ```

  **`src/bot/keyboards/period_picker.py`:**
  ```python
  """Period filter for lists and client history."""
  from __future__ import annotations
  from typing import Literal
  from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
  from src.bot.callback_data import PeriodCD


  def period_picker_kb(*, scope: Literal["lists", "client"], scope_id: int = 0) -> InlineKeyboardMarkup:
      def btn(text: str, kind: str) -> InlineKeyboardButton:
          return InlineKeyboardButton(
              text=text,
              callback_data=PeriodCD(kind=kind, scope=scope, scope_id=scope_id).pack(),  # type: ignore[arg-type]
          )
      rows = [
          [btn("Сегодня", "today"), btn("Неделя", "week"), btn("Месяц", "month")],
          [btn("Все", "all"), btn("📅 Дата", "date")],
      ]
      return InlineKeyboardMarkup(inline_keyboard=rows)
  ```

  **`src/bot/keyboards/client_picker.py`:**
  ```python
  """Recent clients + search + create-new."""
  from __future__ import annotations
  from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
  from src.bot.callback_data import ClientCD
  from src.storage.models import Client


  def client_picker_kb(*, recent: list[Client]) -> InlineKeyboardMarkup:
      rows: list[list[InlineKeyboardButton]] = []
      for c in recent:
          rows.append([
              InlineKeyboardButton(
                  text=c.name,
                  callback_data=ClientCD(action="pick", client_id=c.id).pack(),
              )
          ])
      rows.append([
          InlineKeyboardButton(text="🔍 Поиск", callback_data=ClientCD(action="pick", client_id=-1).pack()),
          InlineKeyboardButton(text="➕ Новый клиент", callback_data=ClientCD(action="new").pack()),
      ])
      return InlineKeyboardMarkup(inline_keyboard=rows)
  ```

  Заметка: `client_id=-1` для «Поиск» — sentinel; в handler'е роутим на ввод запроса. Альтернативно — отдельный CD; здесь экономим.

  **`src/bot/keyboards/confirm.py`:**
  ```python
  """Confirm card actions."""
  from __future__ import annotations
  from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
  from src.bot.callback_data import WizardCD


  def confirm_kb() -> InlineKeyboardMarkup:
      return InlineKeyboardMarkup(inline_keyboard=[[
          InlineKeyboardButton(text="✅ Сохранить", callback_data=WizardCD(action="save").pack()),
          InlineKeyboardButton(text="✏️ Поправить", callback_data=WizardCD(action="edit").pack()),
          InlineKeyboardButton(text="❌ Отмена", callback_data=WizardCD(action="cancel").pack()),
      ]])
  ```

  **`src/bot/keyboards/appointment_card.py`:**
  ```python
  """Per-appointment card actions."""
  from __future__ import annotations
  from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
  from src.bot.callback_data import ApptCD


  def appointment_card_kb(*, appointment_id: int) -> InlineKeyboardMarkup:
      cd = lambda action: ApptCD(action=action, appointment_id=appointment_id).pack()  # type: ignore[arg-type]  # noqa: E731
      return InlineKeyboardMarkup(inline_keyboard=[
          [
              InlineKeyboardButton(text="Перенести", callback_data=cd("move")),
              InlineKeyboardButton(text="Заметка", callback_data=cd("note")),
          ],
          [
              InlineKeyboardButton(text="Отменить", callback_data=cd("cancel")),
              InlineKeyboardButton(text="Закрыть", callback_data=cd("close")),
          ],
      ])
  ```

- [ ] **Step 8.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_keyboards.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/keyboards/ tests/bot/test_keyboards.py
  git commit -m "feat(bot): time/period/client/confirm/card keyboards"
  ```

---

### Task 9: Add appointment FSM-handler (флагман задача)

**Files:**
- Create: `src/bot/handlers/add_appointment.py`
- Create: `tests/bot/test_add_appointment_flow.py`

Самый большой handler. Покрывает:
- Вход через reply-keyboard кнопку «+ Запись» И через `/new` команду.
- Выбор клиента: «➕ Новый» → ввод имени → ввод instagram → продолжение.
- Гибридный выбор даты: `[Сегодня][Завтра][Послезавтра][📅 Календарь][⌨️ Текстом]`.
- Выбор времени: сетка + «Другое время» (свободный ввод HH:MM).
- Опциональная заметка.
- Conflict-чек через `AppointmentRepository.find_overlap`.
- Карточка-подтверждение → save / edit / cancel.

**Структура** (для писателя кода — читать `swirling-whistling-tulip.md` Поток B
параллельно):
- 30+ хендлеров — group по callback типу, не по step'у.
- Все промежуточные тексты — через `ui.advance(...)`.
- Save → `ui.finalize(state, "✅ Запись сохранена\n<карточка>")`.
- Cancel везде → `ui.cancel(state)`.

- [ ] **Step 9.1: Sketch tests first** (минимум — happy path):
  ```python
  """End-to-end FSM happy path for add_appointment."""
  # Полный набор тестов значительный — для краткости здесь skeleton.
  # Имплементатор должен покрыть:
  #   - вход через "+ Запись" (reply text)
  #   - выбор существующего клиента через ClientCD(action="pick")
  #   - выбор "Сегодня" → переход к выбору времени
  #   - выбор "14:00" → переход к заметке
  #   - "Пропустить" → confirm card
  #   - "Сохранить" → запись в БД, finalize
  #   - "Отмена" в любом state → ui.cancel
  #   - конфликт (overlap exists) → диалог "Записать всё равно?"
  #   - ввод HH:MM в свободном виде
  #   - выбор даты через календарь
  #   - выбор даты через "📅 Календарь" → CalendarCD(action="pick")
  #   - переключение месяца через CalendarCD(action="nav")
  ```
  Использовать aiogram's `MockedBot`/`Dispatcher` подход или прямые asyncio
  unit-tests с mock-объектами `Message`/`CallbackQuery` (как в
  `test_whitelist_middleware.py`).

- [ ] **Step 9.2: Implement** `src/bot/handlers/add_appointment.py`. Скелет:
  ```python
  """Add appointment FSM flow — Поток B from spec."""
  from __future__ import annotations
  from datetime import date, datetime, timedelta
  from zoneinfo import ZoneInfo

  from aiogram import F, Router
  from aiogram.filters import Command
  from aiogram.fsm.context import FSMContext
  from aiogram.types import CallbackQuery, Message

  from src.bot.callback_data import CalendarCD, ClientCD, TimeCD, WizardCD
  from src.bot.keyboards.calendar import calendar_kb
  from src.bot.keyboards.client_picker import client_picker_kb
  from src.bot.keyboards.confirm import confirm_kb
  from src.bot.keyboards.time_picker import time_picker_kb
  from src.bot.states import AddAppointment
  from src.bot.ui import advance, cancel, finalize
  from src.services import settings_service
  from src.services.formatters import format_date_ru
  from src.storage import db
  from src.storage.repositories.appointments import AppointmentRepository
  from src.storage.repositories.clients import ClientRepository

  router = Router(name="add_appointment")


  # --- entry points ----------------------------------------------------------

  @router.message(F.text == "+ Запись")
  @router.message(Command("new"))
  async def entry_new(message: Message, state: FSMContext, session_factory) -> None:  # type: ignore[no-untyped-def]
      ...  # detail in implementation
  ```

  Полная имплементация на 250–350 строк — основная работа этой задачи. Опираться на:
  - `swirling-whistling-tulip.md` §Поток B (детальное описание шагов);
  - `swirling-whistling-tulip.md` §«Дисциплина закрытия состояний»;
  - готовый `AppointmentRepository.find_overlap`.

  Заметки по реализации:
  - `session_factory` пробрасывается через `dp["session_factory"]` (см. Task 17 main.py wiring).
  - Каждое использование БД — через `async with db.session_scope(factory) as session:`.
  - При конфликте показывать имя/время уже существующей записи: `format_appointment_line` использовать.
  - Даты собираем naive в локальной TZ → перед сохранением в БД конвертим в UTC: `local.astimezone(timezone.utc).replace(tzinfo=None)`.

- [ ] **Step 9.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_add_appointment_flow.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/handlers/add_appointment.py tests/bot/test_add_appointment_flow.py
  git commit -m "feat(bot): add_appointment FSM flow with conflict check"
  ```

---

### Task 10: `/add` text command handler

**Files:**
- Create: `src/bot/handlers/text_add.py`
- Create: `tests/bot/test_text_add_handler.py`

`/add 2026-05-06 14:30 Олег @oleg маникюр` — парсим через `text_parser`,
ищем/создаём клиента, проверяем конфликт, показываем карточку-подтверждение
(как Поток A в спеке с шага 5).

- [ ] **Step 10.1: Failing tests** in `tests/bot/test_text_add_handler.py`:
  ```python
  # Покрыть:
  #   - валидный /add → карточка с confirm_kb
  #   - невалидный /add → "Не могу разобрать. Попробуй формат: ..."
  #   - конфликт → "В это время Иван Иванов с 14:00 до 15:00. Записать всё равно?"
  #   - существующий клиент по name (case-insensitive) переиспользуется
  ```

- [ ] **Step 10.2: Implement** `src/bot/handlers/text_add.py`. Принципы:
  - Если `parse_add_command` бросил `ParseError` — отвечаем help-строкой
    с примером и `/help` как ссылкой.
  - Если клиент по имени уже есть (через `ClientRepository.search_by_name`,
    точное совпадение) — переиспользуем; иначе создаём.
  - Карточка-подтверждение в state, как в Task 9 (использовать те же helpers).

- [ ] **Step 10.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_text_add_handler.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/handlers/text_add.py tests/bot/test_text_add_handler.py
  git commit -m "feat(bot): /add text command handler with confirm card"
  ```

---

### Task 11: Lists handler (`/today`, `/tomorrow`, `/week`)

**Files:**
- Create: `src/bot/handlers/lists.py`
- Create: `tests/bot/test_lists_handler.py`

Все три команды + соответствующие reply-keyboard кнопки (`📅 Сегодня`,
`📆 Завтра`, `🗓 Неделя`). Используют `period_picker_kb`/`AppointmentRepository.list_in_range`/
`format_appointment_line`/`group_by_day`.

- [ ] **Step 11.1: Failing tests** in `tests/bot/test_lists_handler.py`:
  ```python
  # Покрыть:
  #   - /today, нет записей → "На сегодня записей нет."
  #   - /today с 2 записями → 2 строки в формате "14:00 · Олег · маникюр"
  #   - /week с записями на 3 разных дня → группировка с заголовками
  #     дней (format_date_ru), отсортировано по времени
  #   - reply-keyboard кнопка "📅 Сегодня" эквивалентна /today
  ```

- [ ] **Step 11.2: Implement** `src/bot/handlers/lists.py`:
  - `/today` → диапазон `[now.date 00:00, now.date+1 00:00)` в локальной TZ → UTC.
  - `/tomorrow` → +1 день.
  - `/week` → `[today, today+7d)` + группировка по дням.
  - Каждая строка списка имеет «карточку» как inline-кнопку (`ApptCD(action="view", appointment_id=...)`).
  - Если записей нет — текст «На <период> записей нет.» без клавиатуры.

- [ ] **Step 11.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_lists_handler.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/handlers/lists.py tests/bot/test_lists_handler.py
  git commit -m "feat(bot): /today /tomorrow /week list handlers"
  ```

---

### Task 12: Clients handler (`/clients` + история по периоду)

**Files:**
- Create: `src/bot/handlers/clients.py`
- Create: `tests/bot/test_clients_handler.py`

Сценарий:
1. `/clients` (или reply-keyboard `👥 Клиенты`) → список последних клиентов
   (`ClientRepository.list_recent(limit=20)`) с inline-кнопками; кнопка
   «🔍 Поиск» переводит в `searching_client` state с просьбой ввести запрос.
2. Тап клиента → его карточка (имя, instagram кликабельным URL,
   notes), внизу клавиатура `[История] [Редактировать] [Назад]`.
3. «История» → `period_picker_kb(scope="client", scope_id=…)`.
4. Выбор периода → список визитов в формате `format_appointment_line` сгруппированный
   по дням. Заголовок — `format_period_header(kind, anchor)`. «📅 Дата» уводит
   в `HistoryFilter.entering_date` для ручного ввода YYYY-MM-DD.

- [ ] **Step 12.1: Failing tests** in `tests/bot/test_clients_handler.py`:
  ```python
  # Покрыть:
  #   - /clients вызывает list_recent, рендерит client_picker_kb
  #   - выбор клиента (ClientCD pick) → карточка
  #   - "История" → period_picker_kb появилась
  #   - PeriodCD(kind="month", scope="client", scope_id=N) → правильный
  #     range, group_by_day, заголовок месяца
  #   - PeriodCD(kind="all") → ВСЕ записи клиента (без фильтра по дате)
  #   - PeriodCD(kind="date") → переход в state, ввод даты, фильтр по этому дню
  ```

- [ ] **Step 12.2: Implement** `src/bot/handlers/clients.py`. Расчёт диапазонов:
  - `today/tomorrow` — как в lists.
  - `week` — `[anchor, anchor+7d)`.
  - `month` — `[первое число, +1 месяц)` в локальной TZ.
  - `all` — `list_in_range(start=epoch, end=далёкое будущее)`, либо
    отдельный метод `list_for_client(client_id, statuses)` — добавить
    в `AppointmentRepository`, если нужно. ⚠️ См. ниже.

  ⚠️ **Side-quest:** в текущем `AppointmentRepository` нет метода `list_for_client`.
  Если он нужен, добавить:
  ```python
  async def list_for_client(self, client_id: int, *, statuses=("scheduled","done","cancelled")) -> list[Appointment]:
      stmt = select(Appointment).where(
          Appointment.client_id == client_id,
          Appointment.status.in_(statuses),
      ).order_by(Appointment.starts_at.desc())
      return list((await self._session.execute(stmt)).scalars())
  ```
  Тест и отдельный коммит `feat(storage): AppointmentRepository.list_for_client`
  ДО шага 12.2. Это не нарушает изоляцию слоёв.

- [ ] **Step 12.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_clients_handler.py tests/storage/test_repositories.py -v
  poetry run ruff check src tests && poetry run mypy src
  # 1й коммит
  git add src/storage/repositories/appointments.py tests/storage/test_repositories.py
  git commit -m "feat(storage): AppointmentRepository.list_for_client"
  # 2й коммит
  git add src/bot/handlers/clients.py tests/bot/test_clients_handler.py
  git commit -m "feat(bot): /clients with period-filtered history"
  ```

---

### Task 13: Appointment card handler (move/cancel/note)

**Files:**
- Create: `src/bot/handlers/appointment_card.py`
- Create: `tests/bot/test_appointment_card.py`

При тапе на запись из любого списка (через `ApptCD(action="view", ...)`)
показываем карточку записи с действиями:
- Перенести → новая дата (calendar/text) → новое время → conflict-чек
  → reschedule.
- Заметка → ввод текста → `EditAppointment.entering_note` → сохранение.
- Отменить → подтверждение → `update_status("cancelled")`.
- Закрыть → убираем клавиатуру у карточки.

- [ ] **Step 13.1: Failing tests** — happy path для каждого действия:
  ```python
  # Покрыть:
  #   - "Перенести" → date picker → time picker → reschedule + конфликт-чек
  #   - "Заметка" → ввод текста → update visit_note
  #   - "Отменить" → диалог "Точно? [Да] [Нет]" → status=cancelled
  #   - "Закрыть" → edit_reply_markup(None), state остаётся пустым
  ```

- [ ] **Step 13.2: Implement** `src/bot/handlers/appointment_card.py`:
  - Использует `EditAppointment` states.
  - При reschedule вызывает `AppointmentRepository.find_overlap` с `exclude_id`
    равным id текущей записи.
  - Заметка — простой `await repo.update_visit_note(id, text)`. Это второй
    side-quest: добавить метод в `AppointmentRepository`:
    ```python
    async def update_visit_note(self, appointment_id: int, text: str) -> Appointment | None:
        appt = await self.get(appointment_id)
        if appt is None:
            return None
        appt.visit_note = text
        await self._session.flush()
        return appt
    ```
    Тест + отдельный коммит ДО шага 13.2.

- [ ] **Step 13.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_appointment_card.py tests/storage/test_repositories.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/storage/repositories/appointments.py tests/storage/test_repositories.py
  git commit -m "feat(storage): AppointmentRepository.update_visit_note"
  git add src/bot/handlers/appointment_card.py tests/bot/test_appointment_card.py
  git commit -m "feat(bot): appointment card with move/cancel/note actions"
  ```

---

### Task 14: System handler (`/cancel`, `/help`, error handler)

**Files:**
- Create: `src/bot/handlers/system.py`
- Create: `tests/bot/test_system_handler.py`

- `/cancel` — глобальный handler, **выше** всех FSM router'ов по приоритету,
  чистит state через `ui.cancel(...)`. Работает в любом state.
- `/help` — статичный текст со списком команд.
- Global error-handler — пишет в лог и отвечает «⚠️ Что-то пошло не так»,
  чистит state.

- [ ] **Step 14.1: Failing tests** in `tests/bot/test_system_handler.py`:
  ```python
  # Покрыть:
  #   - /cancel в state → ui.cancel вызывается, state сброшен
  #   - /cancel вне state → "Сейчас нет активного flow."
  #   - /help → текст содержит "/add", "/today", "/clients"
  #   - error_handler вызван → state.clear, отправлено "⚠️"
  ```

- [ ] **Step 14.2: Implement** `src/bot/handlers/system.py`. Регистрация в
  главном dispatcher должна быть **первой** среди routers (см. Task 15).

- [ ] **Step 14.3: Tests + lint + commit**
  ```bash
  poetry run pytest tests/bot/test_system_handler.py -v
  poetry run ruff check src tests && poetry run mypy src
  git add src/bot/handlers/system.py tests/bot/test_system_handler.py
  git commit -m "feat(bot): /cancel, /help, global error handler"
  ```

---

### Task 15: Wire everything in main.py

**Files:**
- Modify: `src/main.py`
- Modify: `tests/bot/test_start_handler.py` (если нужно — поправить fixtures)

- [ ] **Step 15.1: Update `_build_dispatcher`** в `src/main.py`:
  ```python
  from src.bot.handlers import (
      add_appointment as add_appt_handlers,
      appointment_card as appt_card_handlers,
      clients as clients_handlers,
      lists as lists_handlers,
      start as start_handlers,
      system as system_handlers,
      text_add as text_add_handlers,
  )
  from src.bot.middlewares.concurrency import ConcurrencyMiddleware


  def _build_dispatcher(settings: Settings, session_factory) -> Dispatcher:  # type: ignore[no-untyped-def]
      storage = RedisStorage.from_url(...)
      dp = Dispatcher(storage=storage)

      # session_factory доступен всем handler'ам
      dp["session_factory"] = session_factory

      # Whitelist — outer, режет всех чужих
      dp.update.outer_middleware(WhitelistMiddleware(owner_chat_id=settings.owner_chat_id))
      # ConcurrencyMiddleware — на CallbackQuery, защита от двойного клика
      dp.callback_query.middleware(ConcurrencyMiddleware())

      # Order matters — system первым (для /cancel приоритет)
      dp.include_router(system_handlers.router)
      dp.include_router(start_handlers.router)
      dp.include_router(add_appt_handlers.router)
      dp.include_router(text_add_handlers.router)
      dp.include_router(lists_handlers.router)
      dp.include_router(clients_handlers.router)
      dp.include_router(appt_card_handlers.router)
      return dp
  ```

  Обновить `run()` — теперь `_seed_defaults` использует тот же `session_factory`,
  что передаётся в dispatcher (один engine на весь жизненный цикл).

- [ ] **Step 15.2: Run full test suite**
  ```bash
  poetry run pytest -v
  ```
  Ожидание: ВСЕ старые 39 + новые тесты зелёные. Если что-то падает —
  починить **в этом коммите**, не размазывать.

- [ ] **Step 15.3: Lint + commit**
  ```bash
  poetry run ruff check src tests && poetry run mypy src
  git add src/main.py tests/
  git commit -m "feat(bot): wire booking core routers + ConcurrencyMiddleware"
  ```

---

### Task 16: End-to-end smoke (manual, в Docker)

- [ ] **Step 16.1: Запуск**
  ```bash
  docker compose down
  docker compose up --build
  ```
  Лог: `Starting bot, owner=<id> tz=Asia/Almaty stt=openai`, затем
  `Run polling for bot @<your_bot>`.

- [ ] **Step 16.2: Manual checklist** (всё это должно работать)
  - [ ] `/start` — главное меню.
  - [ ] `+ Запись` → выбрать «➕ Новый клиент» → ввести имя «Тест» →
        ввести instagram «—» → выбрать «Сегодня» → выбрать «14:00» →
        ввести заметку «маникюр» → карточка-подтверждение → «✅ Сохранить» →
        получаем «✅ Запись сохранена».
  - [ ] `/today` → показывает только что созданную запись в формате
        `14:00 · Тест · маникюр` с inline-кнопкой.
  - [ ] Тап на эту запись → карточка записи → «Закрыть» → клавиатура исчезает.
  - [ ] `/add 2026-05-07 11:00 Олег @oleg маникюр` → карточка-подтверждение →
        «Сохранить».
  - [ ] `/tomorrow` → видим Олега.
  - [ ] `/week` → видим обе записи сгруппированными по дням.
  - [ ] Создать вторую запись на то же время («сегодня 14:00») →
        диалог «⚠️ В это время Тест с 14:00 до 15:00. Записать всё равно?» →
        «Изменить время» → выбрать другое → сохраняется.
  - [ ] `/clients` → видим обоих клиентов → выбрать «Тест» → «История» →
        выбрать «Сегодня» → видим запись.
  - [ ] Карточка записи → «Перенести» → выбрать новую дату/время → reschedule
        отрабатывает + conflict-check.
  - [ ] Карточка записи → «Заметка» → ввести текст → visit_note обновился.
  - [ ] Карточка записи → «Отменить» → подтверждение → status=cancelled →
        в `/today` не показывается.
  - [ ] Двойной тап по «Сохранить» в карточке-подтверждении — второй
        тап не создаёт дубль (ConcurrencyMiddleware).
  - [ ] `/cancel` посреди FSM — flow прерывается, `❌ Отменено`.
  - [ ] `/help` — текст со списком команд.
  - [ ] С чужого аккаунта `/start` — бот молчит (whitelist).

- [ ] **Step 16.3: Если всё ок — мерж**
  ```bash
  poetry run pytest -v        # final green
  git push -u origin plan/booking-core
  # на GitHub: PR → review → merge to master
  ```

---

## Verification (как проверить end-to-end на CI-уровне)

Помимо manual checklist выше, эти команды должны быть clean:

```bash
poetry run pytest -v --cov=src --cov-report=term-missing
# Ожидание: все тесты зелёные. Покрытие новых модулей ≥ 80%.

poetry run ruff check src tests
poetry run mypy src
```

Граф после мержа автоматически пересоберётся через post-commit hook —
проверить, что новые ноды появились:

```bash
~/.local/bin/graphify update .
~/.local/bin/graphify query "AddAppointment FSM flow"
```

Должны увидеться новые god-nodes: `AddAppointment` (FSM-states),
`add_appointment.router`, `ConcurrencyMiddleware`.

---

## Что НЕ в этом плане (явно)

- **Уведомления** (`scheduled_jobs`, APScheduler, дайджесты) → Plan #3.
- **Голосовой ввод** + LLM-парсер → Plan #4.
- **Yandex SpeechKit** + переключение провайдеров → Plan #4.
- **Recovery FSM на старте бота** + zombie-button дисциплина → Plan #5.
- **Деплой Oracle Cloud + systemd** → Plan #5.
- **Бэкап SQLite** → Plan #5 (open item спеки).

---

## Open items, которые могут вынырнуть при имплементации

1. **`format_period_header` для `kind="date"` с конкретной датой** — anchor
   передаётся снаружи; формат строки уже задан в Task 6.
2. **Что показывать в карточке клиента** — имя, instagram (кликабельная ссылка
   `https://instagram.com/{handle}`), notes (если есть). Кнопки `[История]
   [Редактировать] [Назад]`.
3. **"➕ Новый клиент" мини-FSM** — имя обязателен, instagram можно ввести
   `—` или `пропустить` (текстом или кнопкой `[Пропустить]`), notes пропускаем
   (вводятся отдельно через «Редактировать» в карточке клиента — это уже
   `EditClient` states; полный edit-flow можно вынести в отдельную задачу
   Task 12.5 или объединить).
4. **Таймзоны при сохранении в SQLite**. Сейчас `Appointment.starts_at` без
   tz-info; решено хранить **в UTC, naive**. При сохранении: `local.astimezone(timezone.utc).replace(tzinfo=None)`.
   При показе: `appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)`.
   Все формат-функции принимают `tz` параметром — fixture в тестах.
5. **Длинный visit_note** в `format_appointment_line` — обрезать до 40 символов
   с `…`? Решение: НЕ обрезать в Plan #2 (см. как смотрится на реальных данных).
   Если коряво — отдельный коммит «truncate visit_note in list view» с
   тестом.

Если что-то из этого расходится с реальностью кода после Foundation —
**верить коду**, обновлять план/спеку.
