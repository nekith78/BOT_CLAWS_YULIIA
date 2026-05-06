# Notifications Implementation Plan (Plan #3)

> **For agentic workers:** TDD per task — failing test → impl → ruff/mypy clean → commit. Storage-first; service layer next; bot/handlers last.

**Goal:** добавить уведомления для записей: дайджест в 20:00 накануне с полным списком + точный пинг за 60 минут до каждой записи. Каждое правило настраивается **per-appointment** через `⚙️ Настройки → 🔔 Настройка уведомлений`. Глобальные правила (дефолты) применяются автоматически к каждой новой записи и могут быть переопределены целиком на отдельной записи.

**Architecture context:** Plan #2 закрыт и в `master`. Foundation предоставил модели `NotifyRule` (глобальные правила) и `ScheduledJob` (запланированный пуш с fire_at, sent_at). На том же SQLite через `SQLAlchemyJobStore` запускается APScheduler — переживает рестарт. На каждый create/move/cancel/delete записи **NotifyService** сносит старые `scheduled_jobs` и создаёт новые на основе текущих правил.

**Tech Stack additions:**
- `APScheduler` 3.10 (уже в `pyproject.toml`).
- `SQLAlchemyJobStore` поверх существующей БД (новая таблица `apscheduler_jobs` создаётся автоматически).

**Prerequisites:**
- master содержит Plan #2 booking core.
- Все 153 теста зелёные, ruff/mypy clean.

**Decisions (согласовано с пользователем):**

1. **Дефолтные правила** (применяются ко ВСЕМ новым записям):
   - `time_day_before` `20:00` — дайджест в 20:00 накануне, **формат A**: список всех записей на завтра построчно.
   - `offset_before` `60m` — пинг ровно за 60 минут до записи (без округлений). Формат: «⏰ Через час: 14:00 Олег маникюр».
   - `time_same_day` (09:00) — **выключено**, удаляется из seed.
2. **Per-appointment override**: новая таблица `appointment_notify_overrides`. Если у записи есть строки в этой таблице — они **полностью заменяют** дефолты для этой записи. Если нет — используются глобальные `notify_rules`.
3. **UI**: «настройка уведомлений» отдельный пункт в `⚙️ Настройки`, ведёт на period-picker → список записей → экран правил конкретной записи.
4. **Recovery**: при старте бота, `scheduled_jobs WHERE sent_at IS NULL AND fire_at < NOW() AND fire_at > NOW() − 6h` отправляются с пометкой «⏰ (с задержкой)»; старше 6h помечаются как sent_at=NOW() и игнорируются.
5. **Дайджест дедуплицируется**: если на одну дату 20:00 уже есть scheduled_job kind=`eve_digest` — не плодим, при срабатывании собираем все записи дня единым сообщением.

---

## File Structure

| Путь | Назначение |
|---|---|
| `src/storage/migrations/versions/0002_appointment_notify_overrides.py` | Миграция таблицы |
| `src/storage/repositories/appointment_notify_overrides.py` | CRUD per-appt |
| `src/storage/repositories/scheduled_jobs.py` | CRUD для scheduled_jobs |
| `src/services/notifications/__init__.py` | _Modify_ — re-exports |
| `src/services/notifications/rules.py` | NotifyService: fire_at расчёт, эффективные правила, plan/replace |
| `src/services/notifications/scheduler.py` | APScheduler bootstrap, recovery |
| `src/services/notifications/senders.py` | Формирование и отправка сообщений |
| `src/services/notifications/jobs.py` | Job-handler'ы (digest, ping) |
| `src/bot/handlers/notify_settings.py` | Handler-flow `⚙️ Настройки → 🔔 Настройка уведомлений` |
| `src/bot/keyboards/notify_settings.py` | Клавиатуры экрана настроек |
| `src/bot/states.py` | _Modify_ — добавить `NotifySettings` group |
| `src/bot/callback_data.py` | _Modify_ — `NotifyRuleCD` уже зарезервирован, расширим |
| `src/bot/handlers/system.py` | _Modify_ — заменить `⚙️ Настройки` stub на реальное меню |
| `src/main.py` | _Modify_ — bootstrap scheduler + recovery |
| `src/services/settings_service.py` | _Modify_ — обновить seed defaults |
| `tests/...` | Соответствующие тесты на каждый блок |

---

## Tasks

### Task 1: Branch + дефолтный seed обновить

- [ ] **Step 1.1** Создать ветку `plan/notifications`.
- [ ] **Step 1.2** В `settings_service.DEFAULT_RULES` убрать `("time_same_day", "09:00", True)`, добавить `("offset_before", "60m", True)`. Тест на `seed_defaults` обновить: ожидать 2 правила — `time_day_before/20:00` и `offset_before/60m`.
- [ ] **Step 1.3** ruff/mypy/pytest. Commit: `chore(services): default notification rules — 20:00 day-before + 60m offset`.

### Task 2: Миграция `appointment_notify_overrides`

```sql
CREATE TABLE appointment_notify_overrides (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id  INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,      -- time_day_before | time_same_day | offset_before
    value           TEXT NOT NULL,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      DATETIME NOT NULL
);
CREATE INDEX idx_appt_notify_appt ON appointment_notify_overrides(appointment_id);
```

- [ ] **Step 2.1** Добавить модель `AppointmentNotifyOverride` в `src/storage/models.py` (тот же стиль что и `NotifyRule`).
- [ ] **Step 2.2** Сгенерировать миграцию: `DB_PATH=$(pwd)/data/bot.db poetry run alembic revision --autogenerate -m "appointment_notify_overrides"`.
- [ ] **Step 2.3** Применить локально: `alembic upgrade head` против чистой `data/bot.db`. Откатить и применить заново — должно быть idempotent.
- [ ] **Step 2.4** Тест в `tests/storage/test_models.py`: создать `AppointmentNotifyOverride`, привязать к appointment, проверить cascade delete (удаление appt → пропадают override).
- [ ] **Step 2.5** ruff/mypy/pytest. Commit: `feat(storage): appointment_notify_overrides model + migration`.

### Task 3: AppointmentNotifyOverrideRepository

```python
class AppointmentNotifyOverrideRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def list_for_appointment(self, appointment_id: int) -> list[AppointmentNotifyOverride]: ...
    async def replace_all(
        self, appointment_id: int, rules: list[tuple[str, str, bool]]
    ) -> None: ...
    async def add_one(
        self, appointment_id: int, *, kind: str, value: str, enabled: bool = True
    ) -> AppointmentNotifyOverride: ...
    async def update_enabled(self, override_id: int, enabled: bool) -> AppointmentNotifyOverride | None: ...
    async def delete_one(self, override_id: int) -> bool: ...
```

- [ ] **Step 3.1** Тесты: list_for_appointment пустой, после add — один; replace_all сносит и вставляет; update_enabled toggle; delete_one returns False on missing.
- [ ] **Step 3.2** Имплементация.
- [ ] **Step 3.3** ruff/mypy/pytest. Commit: `feat(storage): AppointmentNotifyOverrideRepository`.

### Task 4: ScheduledJobRepository

```python
class ScheduledJobRepository:
    async def replace_for_appointment(
        self, appointment_id: int, jobs: list[tuple[datetime, str, str | None]]  # (fire_at, kind, job_id)
    ) -> None: ...
    async def list_due_unsent(self, *, now: datetime, max_age_hours: int = 6) -> list[ScheduledJob]: ...
    async def list_overdue_to_skip(self, *, now: datetime, max_age_hours: int = 6) -> list[ScheduledJob]: ...
    async def mark_sent(self, scheduled_job_id: int, *, when: datetime) -> None: ...
    async def find_eve_digest_for_date(self, fire_at: datetime) -> ScheduledJob | None:
        """Дедуп: один dэйджест на дату/время."""
```

- [ ] **Step 4.1** Тесты: replace_for_appointment сносит старые, ставит новые; list_due_unsent возвращает только sent_at IS NULL и в окне; mark_sent заполняет timestamp.
- [ ] **Step 4.2** Имплементация.
- [ ] **Step 4.3** ruff/mypy/pytest. Commit: `feat(storage): ScheduledJobRepository`.

### Task 5: NotifyService — расчёт fire_at и эффективные правила

```python
@dataclass(frozen=True)
class PlannedJob:
    fire_at_utc: datetime  # naive, как в БД
    kind: Literal["eve_digest", "morning_digest", "offset_ping"]
    rule_value: str  # debug

async def effective_rules_for_appointment(
    session: AsyncSession, appointment_id: int
) -> list[tuple[str, str, bool]]:
    """Override list_for_appointment → если непустой, вернуть его. Иначе — глобальные."""

async def plan_jobs(
    session: AsyncSession, appointment: Appointment, *, tz: ZoneInfo
) -> list[PlannedJob]:
    """Для каждого enabled правила (effective) вычислить fire_at_utc:
    - time_day_before "HH:MM": HH:MM в OWNER_TZ за день до starts_at_local → UTC
    - time_same_day "HH:MM":  HH:MM в OWNER_TZ в день starts_at_local → UTC
    - offset_before "60m" / "24h" / "2d": starts_at_utc − offset
    Игнорировать прошедшие fire_at_utc < now().
    """
```

- [ ] **Step 5.1** Тесты: parsing offset (60m, 2h, 1d), TZ-конверсия, фильтр прошедших, override полностью заменяет defaults.
- [ ] **Step 5.2** Имплементация.
- [ ] **Step 5.3** ruff/mypy/pytest. Commit: `feat(services): NotifyService.plan_jobs + effective_rules`.

### Task 6: NotifyService.reschedule_for_appointment + хук

```python
async def reschedule_for_appointment(
    session: AsyncSession,
    *,
    bot: Bot,
    scheduler: AsyncIOScheduler,
    appointment_id: int,
) -> None:
    """1) prep load appt; 2) plan_jobs; 3) replace scheduled_jobs DB-row;
    4) для не-digest: scheduler.add_job(fire_at, ...); 5) для eve_digest:
    дедуп по дате — один scheduled_job + один APScheduler job."""

async def cancel_for_appointment(
    session: AsyncSession, *, scheduler: AsyncIOScheduler, appointment_id: int,
) -> None: ...
```

- [ ] **Step 6.1** Тесты: с моком scheduler — reschedule создаёт правильные jobs, cancel снимает все.
- [ ] **Step 6.2** Имплементация.
- [ ] **Step 6.3** Хуки в `add_appointment.on_save` / `on_force_save`, в `appointment_card.on_move_time_picked` / `on_cancel_confirmed`. Текстовый `/add` тоже.
- [ ] **Step 6.4** ruff/mypy/pytest. Commit: `feat(services): hook NotifyService into appointment lifecycle`.

### Task 7: Senders — форматирование и отправка

```python
async def send_eve_digest(bot: Bot, chat_id: int, appointments: list[tuple[Appointment, Client]], *, tz, late: bool = False) -> None:
    """🔔 Завтра 3 записи:\n11:00 · Олег · маникюр\n14:00 · Аня · педикюр\n..."""

async def send_offset_ping(bot: Bot, chat_id: int, appointment: Appointment, client: Client, *, tz, late: bool = False) -> None:
    """⏰ Через час: 14:00 Олег маникюр  (или: ⏰ (с задержкой) ...)"""
```

- [ ] **Step 7.1** Тесты: формат, late-prefix, html.escape на user-supplied.
- [ ] **Step 7.2** Имплементация.
- [ ] **Step 7.3** ruff/mypy/pytest. Commit: `feat(services): notification message senders`.

### Task 8: APScheduler bootstrap + job functions

```python
def build_scheduler(db_url: str) -> AsyncIOScheduler:
    return AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=db_url.replace("+aiosqlite", ""))},
        timezone=timezone.utc,
    )

# Job entry point — registered with scheduler.add_job:
async def run_eve_digest(scheduled_job_id: int) -> None:
    """Pull appointments for the digest's date, send, mark sent_at."""

async def run_offset_ping(scheduled_job_id: int) -> None:
    """Pull single appt, send, mark sent_at."""
```

- [ ] **Step 8.1** Тесты: build_scheduler возвращает живой; job-функция с моком session выполняет full flow.
- [ ] **Step 8.2** Имплементация.
- [ ] **Step 8.3** ruff/mypy/pytest. Commit: `feat(services): APScheduler bootstrap + job entry points`.

### Task 9: Recovery on startup

```python
async def recover_missed_jobs(
    session: AsyncSession, *, bot: Bot, owner_chat_id: int, tz, now_utc: datetime,
) -> None:
    """1) due_unsent (≤6h) → отправить с late=True, sent_at=NOW().
    2) overdue (>6h) → sent_at=NOW(), не отправлять."""
```

- [ ] **Step 9.1** Тесты: разные age пограничные случаи.
- [ ] **Step 9.2** Имплементация.
- [ ] **Step 9.3** Вызов из `main.py` после `_seed_defaults`. Передать scheduler, owner_chat_id.
- [ ] **Step 9.4** ruff/mypy/pytest. Commit: `feat(services): startup recovery for missed notifications`.

### Task 10: Wire scheduler в main.py

```python
async def run() -> None:
    settings = load_settings()
    ...
    engine = db.create_engine(settings.db_url)
    factory = db.create_session_factory(engine)
    try:
        await _seed_defaults(factory)
        bot = Bot(...)
        scheduler = build_scheduler(settings.db_url)
        scheduler.start()
        try:
            await recover_missed_jobs(...)
            dp = _build_dispatcher(settings, factory, scheduler)
            await dp.start_polling(...)
        finally:
            scheduler.shutdown()
            await bot.session.close()
    finally:
        await engine.dispose()
```

- [ ] **Step 10.1** Передать scheduler в dispatcher через `dp["scheduler"] = scheduler`. Обновить хендлер-сигнатуры (через `**data`).
- [ ] **Step 10.2** Полный pytest должен оставаться зелёным (все handler'ы обновлены).
- [ ] **Step 10.3** ruff/mypy/pytest. Commit: `feat(bot): bootstrap scheduler in main.py + recover on startup`.

### Task 11: Заменить `⚙️ Настройки` stub на меню

`system.py` сейчас отвечает на `⚙️ Настройки` фразой «🚧 Раздел в работе». Заменить:

```
⚙️ Настройки

[🔔 Настройка уведомлений]
[🌍 Часовой пояс — пока: Asia/Almaty]
```

(Остальное — заглушки на Plan #4/#5).

- [ ] **Step 11.1** В `system.py` `handle_settings_stub` (или новый `handle_settings_menu`) — отвечает inline-кнопками. CD: `WizardCD(action="edit")` для уведомлений (или новый `SettingsCD`). Лучше `SettingsCD` для чистоты.
- [ ] **Step 11.2** Тест.
- [ ] **Step 11.3** Commit: `feat(bot): real settings menu replacing the stub`.

### Task 12: Notify settings UI — period picker + список

Нажатие «🔔 Настройка уведомлений» → period_picker_kb(scope="lists") (можно переиспользовать тот же что в `📋 Записи`, или новый scope=`notify_settings` если поведение должно отличаться).

- [ ] **Step 12.1** Расширить `PeriodCD.scope` literal до `["lists", "client", "notify_settings"]`.
- [ ] **Step 12.2** Handler `PeriodCD.filter(F.scope == "notify_settings")` → построить тот же список записей (без дайджест-фильтра, только scheduled), но callback на запись = `NotifyRuleCD(action="edit", rule_id=appt_id_as_proxy)` или новое поле в существующей CD.

   Лучше: `ApptCD(action="note")` слишком далеко. Введу `NotifyRuleCD(action="edit", rule_id=…)` где rule_id используется как appointment_id — нет, это путаница. Сделаю отдельный CD или добавлю в `ApptCD` action="notify" (Literal расширить).
   
   Расширю `ApptCD.action` до `"notify"`. Это новое значение, безопасно.
- [ ] **Step 12.3** Тесты.
- [ ] **Step 12.4** Commit: `feat(bot): notify-settings entry list (period → appointments)`.

### Task 13: Per-appointment notify settings screen

Тап `ApptCD(action="notify", appointment_id=N)` → экран:

```
🔔 Уведомления по записи:
14:00 · Олег · маникюр  (вторник, 12 мая)

Текущие правила:
✅ За день в 20:00     [Выключить]
✅ За 60 мин до визита [Выключить]

[+ Добавить своё]
[← Назад]
```

При первом открытии у записи нет override — показываются дефолты. Любой toggle создаёт row override (полный набор копируется как override базы), потом мутирует.

- [ ] **Step 13.1** Тесты: первый toggle копирует defaults в override, второй toggle меняет один; кнопка «Назад» возвращает к picker; добавление кастомного работает.
- [ ] **Step 13.2** Имплементация. CD: `NotifyRuleCD(action=..., rule_id=...)` (rule_id = override_id, или 0 для глобальных при первом снапшоте).
- [ ] **Step 13.3** Reschedule scheduled_jobs ПОСЛЕ каждого изменения override (вызывать `NotifyService.reschedule_for_appointment`).
- [ ] **Step 13.4** Commit: `feat(bot): per-appointment notify rules screen`.

### Task 14: Mini-FSM добавления своего правила

```
Тип:
[Время дня (накануне)]
[Время дня (в день)]
[За N до визита]
```

- Если "Время дня" → ввод HH:MM (тот же фильтр что в `+ Запись entering_time`).
- Если "За N до" → ввод числа → выбор единицы [мин][часов][дней].

- [ ] **Step 14.1** Новый state group `NotifySettings.adding_rule_kind / adding_rule_time / adding_rule_offset_value / adding_rule_offset_unit`.
- [ ] **Step 14.2** Тесты + handlers.
- [ ] **Step 14.3** После save: `replace_all` в override + reschedule.
- [ ] **Step 14.4** Commit: `feat(bot): add custom notify rule mini-flow`.

### Task 15: Smoke в Docker (manual)

- [ ] Создать запись на завтра 14:00.
- [ ] Подменить системное время на 19:59:50 текущего дня (или подождать) → проверить что в 20:00 пришёл дайджест.
- [ ] Аналогично — за 60м до 14:00 пришёл pinging.
- [ ] Зайти в `⚙️ Настройки → 🔔 Настройка уведомлений` → выбрать запись → отключить «20:00 накануне» → перезапустить-сценарий → дайджест НЕ пришёл, ping пришёл.
- [ ] Перезапуск контейнера за 5 минут до 14:00 (когда ping должен был быть в 13:00) → recovery отправляет «⏰ (с задержкой)».
- [ ] Все 4 пункта — отметить.

### Task 16: Final review + merge

- [ ] Полный pytest, ruff, mypy.
- [ ] Adversarial review через subagent (как делали с Plan #2). Если найдёт критику — починить.
- [ ] `git checkout master && git merge --ff-only plan/notifications`.

---

## Open items

- **Время-зависимые тесты scheduler'а:** APScheduler требует или живого event loop, или mock'а на add_job. В юнит-тестах планируем мок, в интеграционных — мини-loop с `freezegun` если потребуется. Пока в плане — мок.
- **Telethon-подобные edge cases recovery:** что если за время простоя бот пропустил >6h jobs? Пометить sent_at, чтобы не зависало. Сделано в Task 9.
- **DST:** Asia/Almaty DST не имеет, поэтому `time_day_before/20:00` детерминирован. Если пользователь сменит TZ на DST-зону — потенциальный edge case. Игнорируем в Plan #3.
