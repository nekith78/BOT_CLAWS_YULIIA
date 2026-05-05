# Transition bundle (Windows → Mac), 2026-05-06

> Собрано на Windows-машине (e:\BOT_CLAWS_YULIIA) для передачи на Mac.
> Всё, что было в `git`, уже доехало до Mac через `git pull`. Этот файл —
> то, что лежало **вне git** (в `~/.claude/`, gitignored файлах, локальных
> настройках) и без чего Claude на Mac не может продолжить работу.
>
> **Источники, которые ИГНОРИРОВАЛ:**
> - `~/.claude/plans/hazy-tinkering-kay.md` — про установку расширения
>   Claude в VS Code на Windows, к проекту не относится.
> - `~/.claude/plans/https-github-com-ruvnet-ruflo-golden-lemur.md` — план
>   аудита репозитория ruflo, к проекту не относится.

---

## 1. Spec: swirling-whistling-tulip.md

> Источник: `~/.claude/plans/swirling-whistling-tulip.md` (809 строк).
> Полная спецификация проекта — единственный source of truth для решений,
> которые ещё не превратились в код. Foundation milestone (этап 1 в конце
> файла) **уже сделан и закоммичен** — см. `docs/superpowers/plans/2026-05-05-foundation.md`.

# План: BOT_CLAWS_YULIIA — Telegram-бот для учёта записей клиентов

## Context

Личный single-user Telegram-бот для мастера (Юлия / владелец `OWNER_CHAT_ID`).
Цель — максимально быстрый и удобный ввод записей клиентов с уведомлениями
накануне и в день визита. Главная фича-флагман — **создание записи голосовым
сообщением**: бот распознаёт речь, парсит её через LLM в структурированную
запись и просит подтверждения. Альтернативы — пошаговая FSM-форма с гибридным
выбором даты/времени и однострочная текстовая команда.

Исходные требования пользователя:
- Один пользователь (whitelist `chat_id`, никакой регистрации)
- Хостинг — Oracle Cloud Free VM (Linux, 24/7)
- Стек — Python 3.12 + aiogram 3, SQLite + SQLAlchemy 2.0 async, Alembic
- TZ — `Asia/Almaty` (UTC+5)
- STT — dual provider: OpenAI Whisper (default) + Yandex SpeechKit (fallback,
  переключение через `.env` без правки кода)
- LLM-парсер — `gpt-4o-mini`
- Дефолтный пресет уведомлений — 20:00 накануне + 09:00 утром (сводный дайджест)
- Гибкая настройка уведомлений **через UI бота** (а не через правку кода)
- Redis для FSM с восстановлением прерванного flow и аккуратным управлением
  inline-кнопками (no zombie buttons, terminal steps strip keyboards)
- Безопасность: ничего секретного в коде, репо публикуется на GitHub
- Длительность визита — 60 мин жёстко (только для проверки конфликтов),
  пользователю в UI **не показываем** при создании записи

Проект greenfield — каталог `e:\BOT_CLAWS_YULIIA` пустой, существующего кода
переиспользовать нечего.

---

## Архитектура

### Слои

```
src/
├── bot/                  # presentation: aiogram-хендлеры, клавиатуры, FSM
│   ├── handlers/
│   │   ├── start.py            # /start, главное меню
│   │   ├── add_appointment.py  # FSM-флоу создания записи
│   │   ├── voice_intake.py     # приём voice → STT → LLM → подтверждение
│   │   ├── text_add.py         # /add команда + /add со свободным текстом
│   │   ├── lists.py            # /today, /tomorrow, /week
│   │   ├── clients.py          # /clients, карточка клиента, история
│   │   ├── appointment_card.py # карточка записи: перенести / отменить / заметки
│   │   ├── settings.py         # /settings: TZ, времена, пресеты, своя настройка
│   │   └── system.py           # /cancel, /help, /restore_session, error handler
│   ├── keyboards/
│   │   ├── main_menu.py
│   │   ├── calendar.py         # inline-календарь (свой, на месяц)
│   │   ├── time_picker.py      # пресеты времени с шагом 30 мин + "другое"
│   │   ├── client_picker.py    # выбор клиента: поиск + список + "+ Новый"
│   │   └── confirm.py          # карточка-подтверждение записи
│   ├── middlewares/
│   │   ├── whitelist.py        # режет всех кроме OWNER_CHAT_ID, логирует попытки
│   │   ├── concurrency.py      # in-memory lock по (chat_id, message_id)
│   │   └── logging.py          # структурированные логи + masking
│   ├── callback_data.py        # типизированные CallbackData factories (v=1)
│   ├── states.py               # FSM-states (AddAppointment, EditClient, …)
│   └── ui.py                   # хелперы: edit_or_send, strip_keyboard, finalize
│
├── services/             # доменная логика, не знают про aiogram
│   ├── appointments.py         # CRUD, проверка конфликтов времени
│   ├── clients.py              # CRUD, поиск по имени (LIKE + транслит)
│   ├── notifications/
│   │   ├── scheduler.py        # AsyncIOScheduler (APScheduler), startup/recovery
│   │   ├── rules.py            # CRUD notify_rules, расчёт fire_at для записи
│   │   └── senders.py          # форматирование и отправка пуш-сообщений
│   ├── voice/
│   │   ├── provider.py         # Protocol STTProvider
│   │   ├── openai_stt.py       # Whisper-1 implementation
│   │   ├── yandex_stt.py       # Yandex SpeechKit v3 (gRPC или REST)
│   │   └── factory.py          # build_stt_provider(settings) — выбор по env
│   ├── parser/
│   │   ├── llm_parser.py       # GPT-4o-mini → ParsedAppointment(name, dt, ig, notes, confidence)
│   │   ├── text_parser.py      # быстрый regex для /add, fallback на LLM
│   │   └── instagram.py        # нормализация ник/url
│   └── settings_service.py     # чтение/запись `settings` (TZ, пресет, default_duration)
│
├── storage/
│   ├── db.py                   # engine, session_factory (async)
│   ├── models.py               # Client, Appointment, NotifyRule, ScheduledJob, Setting
│   ├── repositories.py         # ClientRepo, AppointmentRepo, NotifyRuleRepo
│   └── migrations/             # alembic
│
├── config.py                   # pydantic-settings: Settings(BaseSettings)
└── main.py                     # bootstrap: bot, dispatcher, scheduler, redis, recovery
```

### Внешние сервисы

```
docker-compose.yml
├── bot     (python:3.12-slim, our code)
└── redis   (redis:7-alpine, AOF persistence)

volumes:
├── data        → /data         (SQLite DB + APScheduler jobstore + logs/)
└── redis-data  → /data         (Redis AOF)
```

---

## Схема БД (SQLite, миграции через Alembic)

```sql
-- Клиент: постоянные атрибуты человека
CREATE TABLE clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    instagram   TEXT,                    -- нормализованный handle без @
    notes       TEXT,                    -- постоянные заметки о клиенте
    created_at  DATETIME NOT NULL,
    UNIQUE(name COLLATE NOCASE)          -- предупреждение при дубликате
);
CREATE INDEX idx_clients_name ON clients(name COLLATE NOCASE);

-- Запись: один визит
CREATE TABLE appointments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id     INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    starts_at     DATETIME NOT NULL,     -- в UTC
    duration_min  INTEGER NOT NULL DEFAULT 60,
    visit_note    TEXT,                  -- заметка к конкретному визиту
    status        TEXT    NOT NULL DEFAULT 'scheduled',
                                         -- scheduled | done | cancelled
    created_at    DATETIME NOT NULL
);
CREATE INDEX idx_appt_starts ON appointments(starts_at, status);
CREATE INDEX idx_appt_client ON appointments(client_id);

-- Правила уведомлений (UI-настраиваемые)
CREATE TABLE notify_rules (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    kind      TEXT NOT NULL,             -- time_day_before | time_same_day | offset_before
    value     TEXT NOT NULL,             -- "20:00" | "09:00" | "60m" | "24h"
    enabled   INTEGER NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL
);

-- Запланированные пуши (привязка APScheduler-job → запись)
CREATE TABLE scheduled_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id  INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
    rule_id         INTEGER REFERENCES notify_rules(id) ON DELETE SET NULL,
    fire_at         DATETIME NOT NULL,   -- в UTC
    kind            TEXT NOT NULL,       -- eve_digest | morning_digest | offset_ping
    job_id          TEXT,                -- ID в APScheduler-store
    sent_at         DATETIME             -- NULL пока не отправлено
);
CREATE INDEX idx_jobs_fire ON scheduled_jobs(fire_at, sent_at);

-- Глобальные настройки (key/value)
CREATE TABLE settings (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
--- ключи: timezone, notify_preset, default_duration_min, stt_provider_override
-- default_duration_min используется ТОЛЬКО для проверки конфликтов;
-- меняется через /settings → Дополнительно → "Длительность визита по умолчанию".
-- В UI создания записи и в карточке записи — не показывается.
```

**Дефолтный seed при первом запуске:**
- `settings`: `timezone=Asia/Almaty`, `notify_preset=eve_morning`, `default_duration_min=60`
- `notify_rules`: два правила — `time_day_before=20:00 enabled` и `time_same_day=09:00 enabled`

---

## Ключевые потоки

### Поток A — Голосовая запись (флагман)

1. `voice_intake.py` ловит `MessageType.VOICE` от owner.
2. Скачивает `.ogg` во временный файл, удаляет файл сразу после STT (даже при ошибке).
3. `STTProvider.transcribe(audio_path) → str` (выбор реализации через `factory.build_stt_provider`).
4. `LLMParser.parse(text) → ParsedAppointment`:
   - Вход: распознанный текст + контекст (текущая дата/время в `Asia/Almaty`,
     список существующих клиентов с их id и instagram для матчинга по имени).
   - Выход: JSON с полями `client_name`, `client_id_guess`, `starts_at_iso`,
     `instagram`, `visit_note`, `confidence` (0..1).
   - Если `client_id_guess` есть — запись привязывается к существующему клиенту.
5. Бот шлёт **карточку-подтверждение**:
   ```
   📝 Распознал:
   👤 Олег Иванов  (новый клиент)
   📅 6 мая (вт), 14:00
   📷 oleg_insta
   📝 маникюр

   [✅ Сохранить] [✏️ Поправить] [❌ Отмена]
   ```
6. **Сохранить** → создаём клиента (если новый) и запись, проверяем конфликт,
   планируем уведомления, кнопки убираем, сообщение становится финальной карточкой.
7. **Поправить** → переход в FSM-форму с предзаполненными полями.
8. **Отмена** → кнопки убираются, сообщение → "❌ Отменено".
9. При `confidence < 0.7` или отсутствии обязательных полей — сразу открывается
   FSM-форма с предзаполненными полями (минуя карточку).

### Поток B — FSM-форма (`+ Запись` из меню)

```
[Шаг 1] Выбор клиента
  → Inline-список последних клиентов + "🔍 Поиск" + "+ Новый клиент"
  → Если "Новый" — мини-под-FSM: имя → instagram (можно "—") → опциональные заметки

[Шаг 2] Когда (гибрид)
  → Кнопки: [Сегодня] [Завтра] [Послезавтра] [📅 Календарь] [⌨️ Текстом]
  → Календарь — собственная inline-сетка месяца (стрелки навигации)
  → Текстом — приём свободного ввода, парсинг через text_parser → fallback LLM

[Шаг 3] Время
  → Сетка: 09:00 09:30 10:00 … 19:00 19:30 20:00 + кнопка [Другое время]
  → "Другое время" — приём свободного ввода (HH:MM)

[Шаг 4] Заметка к визиту (опционально)
  → "Что делаем?" + кнопка [Пропустить]

[Шаг 5] Конфликт?
  → Если в (starts_at, starts_at + duration) уже есть scheduled-запись:
    "⚠️ В это время Олег с 14:00 до 15:00. Записать всё равно?"
    [Записать] [Изменить время] [Отмена]

[Шаг 6] Финальная карточка → Сохранить / Изменить
```

### Поток C — Текстовая команда

`/add 2026-05-06 14:30 Олег @oleg_insta маникюр` — парсинг через `text_parser`
(жёсткий regex). Если строка не распознаётся — fallback на тот же `llm_parser`,
далее как в Потоке A с шага 5.

### Поток D — Уведомления

**На создание/перенос/отмену записи:**
1. Удалить старые `scheduled_jobs` для этой `appointment_id`.
2. Прочитать активные `notify_rules` (через `notifications.rules.get_enabled()`).
3. Для каждого правила вычислить `fire_at` относительно `appointment.starts_at`:
   - `time_day_before` "20:00" → 20:00 в `Asia/Almaty` за день до визита
   - `time_same_day`  "09:00" → 09:00 в `Asia/Almaty` в день визита
   - `offset_before`  "60m" / "24h" → `starts_at − offset`
4. Записать в `scheduled_jobs` + добавить в APScheduler-store
   (`SQLAlchemyJobStore` поверх той же БД — переживает рестарты).
5. **Дайджесты** (`time_*`) дедуплицируются: если на тот же `fire_at` уже
   запланирован дайджест — не плодим, при срабатывании собираем все записи дня.

**На срабатывание job'а:**
- `eve_digest`/`morning_digest` — собирает все `scheduled` записи на нужный
  день и шлёт одно сводное сообщение (имя, время, инста-ссылка кликабельная).
- `offset_ping` — шлёт пуш по конкретной записи.
- Помечает `scheduled_jobs.sent_at = NOW()`.

**Recovery на старте бота:**
- Просканировать `scheduled_jobs WHERE sent_at IS NULL AND fire_at < NOW()
  AND fire_at > NOW() − 6h` → отправить с пометкой "⏰ (с задержкой)".
- Старше 6h — пропустить, пометить `sent_at = NOW()` чтобы не зависало.

### Поток E — Настройки уведомлений (`/settings → Уведомления`)

```
Текущий пресет: ▶ Утренний + Вечерний дайджест

[ Только вечером (20:00 накануне) ]
[▶ Вечером + утром ]                ← дефолт
[ Вечером + за час до визита ]
[ ⚙️ Своя настройка ]
```

**`/settings` верхний уровень** — пункты:
- 🌍 Часовой пояс
- 🔔 Уведомления (см. ниже)
- 🎙 STT-провайдер (отображение текущего; смена — через `.env` + рестарт)
- 🛠 Дополнительно → 🔢 Длительность визита по умолчанию (60 мин, скрытая
  служебная настройка для проверки конфликтов)

**"⚙️ Своя настройка"** — экран со списком правил:
```
Активные напоминания:
✅ За день в 20:00       [Изменить] [Выключить]
✅ В день в 09:00        [Изменить] [Выключить]
☐ За 1 час до визита    [Включить]
☐ За 24 часа до визита  [Включить]

[+ Добавить своё]
[← Назад]
```

**"+ Добавить своё"** — мини-FSM:
1. Тип правила: [Время дня (накануне)] [Время дня (в день)] [За N до визита]
2. Если "Время дня": ввод HH:MM → сохранение
3. Если "За N до": ввод числа → выбор единицы [мин][часов][дней] → сохранение
4. После сохранения — пересоздание `scheduled_jobs` для всех будущих записей.

**Переключение пресета затирает кастомные правила.** Если в `notify_rules` есть
правила, не входящие в выбираемый пресет, бот сначала спрашивает:
```
⚠️ У тебя есть свои правила (например, "За 1ч до визита").
При смене на «Вечером + утром» они удалятся.
[Заменить] [Оставить свои + добавить из пресета] [Отмена]
```
После выбора — `notify_rules` обновляется по сценарию, `scheduled_jobs`
пересоздаются для всех будущих записей.

---

## Безопасность

### Конфиг и секреты

`src/config.py` — `pydantic-settings`:
```python
class Settings(BaseSettings):
    bot_token: SecretStr
    owner_chat_id: int
    owner_tz: str = "Asia/Almaty"

    stt_provider: Literal["openai", "yandex"] = "openai"
    openai_api_key: SecretStr | None = None
    yandex_api_key: SecretStr | None = None
    yandex_folder_id: str | None = None

    llm_model: str = "gpt-4o-mini"
    llm_api_key: SecretStr | None = None  # = openai_api_key по умолчанию

    redis_url: str = "redis://redis:6379/0"
    db_path: str = "/data/bot.db"

    log_level: str = "INFO"
    fsm_ttl_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def _validate_provider_keys(self):
        if self.stt_provider == "openai" and not self.openai_api_key:
            raise ValueError("STT_PROVIDER=openai requires OPENAI_API_KEY")
        if self.stt_provider == "yandex" and not (self.yandex_api_key and self.yandex_folder_id):
            raise ValueError("STT_PROVIDER=yandex requires YANDEX_API_KEY and YANDEX_FOLDER_ID")
        return self
```

Бот падает на старте с понятным сообщением, если обязательные ключи не заданы.
**Никаких хардкоженных значений в коде.**

### `.env.example` (комитится)

```dotenv
# Telegram
BOT_TOKEN=
OWNER_CHAT_ID=
OWNER_TZ=Asia/Almaty

# STT provider: openai | yandex
STT_PROVIDER=openai

# OpenAI (Whisper + LLM)
OPENAI_API_KEY=

# Yandex SpeechKit (если STT_PROVIDER=yandex)
YANDEX_API_KEY=
YANDEX_FOLDER_ID=

# LLM
LLM_MODEL=gpt-4o-mini

# Infra
REDIS_URL=redis://redis:6379/0
DB_PATH=/data/bot.db

# UX
FSM_TTL_MINUTES=30
LOG_LEVEL=INFO
```

### `.gitignore` (полный)

```gitignore
# Secrets
.env
.env.local
.env.*.local

# Database (содержит данные клиентов!)
data/
*.db
*.db-journal
*.db-wal
*.db-shm
*.sqlite
*.sqlite3
*.sqlite-journal

# Redis dumps
dump.rdb
appendonly.aof
*.aof
*.rdb

# Logs (могут содержать chat_id и фрагменты сообщений)
logs/
*.log
*.log.*

# Voice cache
voice_cache/
audio_temp/
*.ogg.tmp

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
.venv/
venv/
env/
ENV/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
*.egg-info/
build/
dist/

# Tooling
.idea/
.vscode/
*.swp
*.swo
.DS_Store
Thumbs.db

# Alembic локальные временные
alembic.ini.local
```

### Дополнительные меры

- **Логи**: `SecretMaskingFilter` в `bot/middlewares/logging.py` — regex маскирует
  токены вида `bot\d+:[\w-]+`, `sk-[\w-]+`, `AQVN[\w-]+` в любом logged-сообщении.
- **Volume**: при первом запуске `chmod 600 /data/bot.db` через init-команду в Dockerfile.
- **Голосовые**: `.ogg` скачивается в `tempfile.NamedTemporaryFile(delete=False)`,
  удаляется в `try/finally` после STT — никакого долгоживущего кэша.
- **Pre-commit hook (опционально)**: `gitleaks` через `pre-commit` — ловит
  случайно закомиченные ключи. Конфиг `.pre-commit-config.yaml` в репо.
- **Whitelist-middleware**: первая строка обработки — если `from_user.id !=
  OWNER_CHAT_ID`, логируем и молча игнорируем (без ответа, чтобы не палить
  существование бота). Применяется к **всем** типам апдейтов.

---

## FSM, Redis и дисциплина по кнопкам

### Storage

```python
# main.py
storage = RedisStorage.from_url(
    settings.redis_url,
    state_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
    data_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
)
dp = Dispatcher(storage=storage)
```

TTL применяется к каждому FSM-ключу — Redis сам удаляет залежавшийся state.

### CallbackData factories

`bot/callback_data.py`:
```python
class ApptCD(CallbackData, prefix="appt", sep="|"):
    v: int = 1                       # версия схемы
    action: Literal["view", "move", "cancel", "note", "client"]
    appointment_id: int

class ClientCD(CallbackData, prefix="client", sep="|"):
    v: int = 1
    action: Literal["pick", "view", "edit", "history"]
    client_id: int

class CalendarCD(CallbackData, prefix="cal", sep="|"):
    v: int = 1
    action: Literal["pick", "nav", "noop"]
    iso_date: str = ""               # YYYY-MM-DD
    nav: str = ""                    # prev|next

class TimeCD(CallbackData, prefix="time", sep="|"):
    v: int = 1
    hhmm: str                        # "14:00" | "custom"

class NotifyRuleCD(CallbackData, prefix="nr", sep="|"):
    v: int = 1
    action: Literal["toggle", "edit", "delete", "preset", "add"]
    rule_id: int = 0
    preset: str = ""
```

При изменении схемы — повышаем `v`, фильтр режет старые callbacks с дружелюбным
ответом "сообщение устарело, открой меню заново".

### Принцип "одно активное FSM-сообщение"

В FSM-state хранится `flow_message_id` (id сообщения с текущими кнопками
flow'а). На каждом шаге **редактируется именно оно** через `edit_text` +
`edit_reply_markup`. `bot/ui.py` предоставляет хелперы:
- `await ui.advance(message, text, kb, state)` — редактирует `flow_message_id`,
  не плодит новые сообщения.
- `await ui.finalize(state, text)` — редактирует в финальный текст БЕЗ кнопок,
  чистит state.
- `await ui.cancel(state)` — финализирует с "❌ Отменено", чистит state.

### Дисциплина закрытия состояний

| Событие | Действие |
|---|---|
| Успешное "Сохранить" | `ui.finalize(state, "✅ Запись сохранена\n<details>")` |
| "Отмена" в любом FSM | `ui.cancel(state)` |
| `/cancel` команда | глобальный handler (priority выше FSM-router'ов) → `ui.cancel(state)` |
| Idle > FSM_TTL | Redis сам очищает; на следующем взаимодействии бот стартует с главного меню |
| Необработанная ошибка | глобальный error-handler: пишет лог, шлёт `"⚠️ Что-то пошло не так"`, `state.clear()` |
| Нажатие старой кнопки (запись удалена/version mismatch) | `answer_callback_query("Сообщение устарело", show_alert=True)` + `edit_reply_markup(None)` |
| Нажатие старой кнопки (запись жива, кнопка валидна) | обрабатываем нормально |
| Двойной тап по "Сохранить" | `concurrency.py` middleware: in-memory lock по `(chat_id, message_id)`, второй клик игнорируется |

### Восстановление flow на старте

`main.py` после старта проверяет — если у `OWNER_CHAT_ID` есть FSM-state в
Redis (значит, бот рестартнул посреди flow'а) — отправляет новое сообщение:
```
🔄 У тебя был незавершённый процесс: «Запись для Олега, выбор времени».
Что делаем?
[▶️ Продолжить] [❌ Отменить]
```
"Продолжить" → возврат в state с восстановлением `flow_message_id` на новое
сообщение. "Отменить" → `state.clear()`.

---

## STT абстракция (легко переключаемые провайдеры)

```python
# services/voice/provider.py
class STTProvider(Protocol):
    name: str
    async def transcribe(self, audio_path: Path) -> TranscriptionResult: ...

@dataclass
class TranscriptionResult:
    text: str
    duration_sec: float
    provider: str
    raw: dict  # для отладки/логов
```

```python
# services/voice/factory.py
def build_stt_provider(settings: Settings) -> STTProvider:
    match settings.stt_provider:
        case "openai":
            return OpenAIWhisperProvider(api_key=settings.openai_api_key.get_secret_value())
        case "yandex":
            return YandexSpeechKitProvider(
                api_key=settings.yandex_api_key.get_secret_value(),
                folder_id=settings.yandex_folder_id,
            )
```

`OpenAIWhisperProvider` — `openai` Python SDK, `audio.transcriptions.create(
model="whisper-1", file=...)`.
`YandexSpeechKitProvider` — REST `https://stt.api.cloud.yandex.net/speech/v1/stt:recognize`
(синхронный, до 30 сек аудио — для голосовых TG это норма; для длиннее —
асинхронный API позже).

Переключение — одна переменная в `.env`, рестарт контейнера.

---

## Деплой (Oracle Cloud Free)

### Dockerfile (multi-stage)

```dockerfile
# --- builder
FROM python:3.12-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir poetry==1.8.3
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.in-project true && \
    poetry install --only main --no-root --no-ansi

# --- runtime
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY src/ ./src/
COPY alembic.ini ./
RUN useradd -m -u 1000 bot && chown -R bot:bot /app
USER bot
CMD ["python", "-m", "src.main"]
```

### docker-compose.yml

```yaml
services:
  bot:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
    depends_on:
      - redis
    command: sh -c "alembic upgrade head && python -m src.main"

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes", "--save", "60", "1"]
    volumes:
      - ./redis-data:/data
```

### systemd unit (на VM)

`/etc/systemd/system/bot-claws.service`:
```ini
[Unit]
Description=BOT_CLAWS_YULIIA
Requires=docker.service
After=docker.service

[Service]
WorkingDirectory=/opt/bot-claws
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down
Restart=always

[Install]
WantedBy=multi-user.target
```

`systemctl enable --now bot-claws.service` — бот стартует при загрузке VM.

---

## Тестирование

- **pytest + pytest-asyncio**, изоляция через in-memory SQLite (`sqlite+aiosqlite:///:memory:`).
- **Unit (services/)**:
  - `appointments`: CRUD, проверка конфликтов (overlap-кейсы)
  - `clients`: поиск по имени (case-insensitive, частичное совпадение)
  - `parser/llm_parser`: с моком LLM-ответа — корректный JSON парсится в `ParsedAppointment`
  - `parser/text_parser`: набор тест-кейсов на `/add`-формат
  - `notifications/rules`: расчёт `fire_at` для всех типов правил с TZ-edge-cases (DST, переходы суток)
- **Mocks**:
  - `FakeSTTProvider` — возвращает заранее заготовленные транскрипции
  - `FakeLLMClient` — возвращает заранее заготовленные JSON-ответы
- **Integration (handlers/)**:
  - aiogram-tests: эмуляция Update'ов, проверка переходов FSM, ожидаемых сообщений и кнопок
  - Сценарии: голос → подтверждение → сохранение; FSM-форма full happy path; конфликт времени; `/cancel` в каждом state'е; зомби-кнопка после удаления записи
- **Manual checklist** (запускается перед каждым деплоем):
  - [ ] Все три способа создания записи работают
  - [ ] Конфликт времени ловится и предупреждает
  - [ ] Уведомления приходят (через подмену `now()` в тестовом режиме)
  - [ ] Переключение `STT_PROVIDER=openai|yandex` работает без правки кода
  - [ ] Whitelist режет чужой `chat_id`
  - [ ] Recovery: остановить бота посреди FSM, рестарт → восстановление flow
  - [ ] Зомби-кнопки: удалить запись через одно сообщение, тапнуть на её кнопку из другого

---

## Критичные файлы (что создаём)

```
e:\BOT_CLAWS_YULIIA\
├── .env.example                             # шаблон без значений
├── .gitignore                               # см. секцию выше
├── .pre-commit-config.yaml                  # gitleaks (опционально)
├── README.md                                # как запустить, .env, деплой
├── pyproject.toml                           # poetry: aiogram, sqlalchemy[asyncio],
│                                            # aiosqlite, alembic, redis, pydantic-settings,
│                                            # apscheduler, openai, httpx, pytz/zoneinfo,
│                                            # structlog, pytest, pytest-asyncio
├── poetry.lock
├── alembic.ini
├── Dockerfile
├── docker-compose.yml
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── callback_data.py
│   │   ├── states.py
│   │   ├── ui.py
│   │   ├── handlers/{start,add_appointment,voice_intake,text_add,
│   │   │             lists,clients,appointment_card,settings,system}.py
│   │   ├── keyboards/{main_menu,calendar,time_picker,client_picker,confirm}.py
│   │   └── middlewares/{whitelist,concurrency,logging}.py
│   ├── services/
│   │   ├── appointments.py
│   │   ├── clients.py
│   │   ├── settings_service.py
│   │   ├── notifications/{scheduler,rules,senders}.py
│   │   ├── voice/{provider,openai_stt,yandex_stt,factory}.py
│   │   └── parser/{llm_parser,text_parser,instagram}.py
│   └── storage/
│       ├── db.py
│       ├── models.py
│       ├── repositories.py
│       └── migrations/
│           ├── env.py
│           └── versions/0001_initial.py
└── tests/
    ├── conftest.py
    ├── unit/{test_appointments,test_clients,test_parsers,test_rules}.py
    └── integration/{test_voice_flow,test_fsm_form,test_notifications}.py
```

---

## Verification (как проверить end-to-end)

После имплементации и `alembic upgrade head`:

1. **Локальный smoke-test (без Oracle Cloud)**:
   ```
   docker compose up --build
   ```
   В Telegram пишем `/start` → должно прийти главное меню.

2. **Проверка whitelist**:
   - С чужого аккаунта пишем `/start` → бот молчит, в логах bot — запись
     `"unauthorized chat_id=… username=…"`.

3. **Голосовой ввод**:
   - Записываем "запиши Олега завтра в два часа дня инста oleg_insta маникюр".
   - Бот → карточка-подтверждение с правильно распознанными полями.
   - "Сохранить" → запись в БД, `scheduled_jobs` создан.

4. **Конфликт**:
   - Создаём вторую запись на то же время → бот предупреждает.

5. **Уведомления**:
   - Меняем системное время на VM (или используем тестовый mode с подменой
     `datetime.now`) на момент за 1 мин до `notify_time` → должен прилететь дайджест.

6. **Переключение STT**:
   - В `.env` ставим `STT_PROVIDER=yandex`, рестарт `docker compose restart bot`.
   - Голосовое всё равно успешно распознаётся (через Yandex).

7. **Recovery**:
   - Начинаем FSM-форму, доходим до шага 3.
   - `docker compose restart bot`.
   - На старте бот шлёт "У тебя был незавершённый процесс… Продолжить?".
   - "Продолжить" → flow восстанавливается на нужном шаге.

8. **Зомби-кнопка**:
   - В `/today` тапаем "Отменить" на записи — она удаляется.
   - В другом сообщении (например, в дайджесте) тапаем кнопку этой же записи →
     бот отвечает alert'ом "запись больше не существует", не падает.

9. **Безопасность репо** (перед `git push`):
   - `git status` не показывает `.env`, `data/`, `logs/`, `dump.rdb`.
   - `git ls-files | grep -E '\.(env|db|sqlite|log|rdb|aof)$'` — пусто.
   - (Опционально) `gitleaks detect --source .` — clean.

10. **Деплой на Oracle Cloud**:
    - SSH на VM, `git clone …`, `cp .env.example .env`, заполняем секреты.
    - `docker compose up -d`, `systemctl enable --now bot-claws.service`.
    - Rebooting VM → бот автоматически стартует.

---

## Этапы реализации (для последующего writing-plans)

Этот документ — спецификация. Дальше через `writing-plans` режется на
исполняемые шаги. Предварительная нарезка:

1. Скаффолд: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`,
   `Dockerfile`, `docker-compose.yml`, `alembic init`. **← СДЕЛАНО (Foundation)**
2. `config.py` + базовый `main.py` (стартует, проверяет Redis, шлёт `/start`). **← СДЕЛАНО**
3. БД-модели + первая миграция + репозитории + seed дефолтных настроек. **← СДЕЛАНО**
4. Whitelist-middleware + главное меню + `/start`. **← СДЕЛАНО**
5. FSM-форма создания записи (без голоса, без LLM): client picker → date
   гибрид → time → save. Конфликт-чек. **← Plan #2 — Booking core (next)**
6. Списки: `/today`, `/tomorrow`, `/week`, карточка записи (перенести/отменить/заметки). **← Plan #2**
7. `/clients` + история клиента + редактирование клиента. **← Plan #2**
8. `notifications`: rules, scheduler, senders, recovery на старте. Дефолтный пресет. **← Plan #3**
9. `/settings`: TZ, пресеты, "Своя настройка" (FSM добавления/редактирования правил). **← Plan #3**
10. STT-абстракция + `OpenAIWhisperProvider`. Поток "голос → текст в чат для
    проверки" (без парсера). **← Plan #4**
11. LLM-парсер + карточка-подтверждения. Поток "голос → запись". **← Plan #4**
12. `YandexSpeechKitProvider` + переключение через env. **← Plan #4**
13. Текстовая команда `/add` (text_parser + LLM fallback). **← Plan #4**
14. Recovery FSM на старте + зомби-кнопок дисциплина (вылизать UX). **← Plan #5**
15. Тесты: unit + integration. Manual checklist — приёмка. **← Plan #5**
16. Деплой на Oracle Cloud, systemd, проверка end-to-end. **← Plan #5**

---

## 2. Other plans / specs

Других специфичных планов для проекта в `~/.claude/plans/` нет. Foundation plan
(`docs/superpowers/plans/2026-05-05-foundation.md`, 2362 строки) лежит в git
и доступен на Mac через `git pull` — дублировать не нужно.

---

## 3. Project memory

> Источник: `~/.claude/projects/e--BOT-CLAWS-YULIIA/memory/`
> Формат сохранён в точности — на Mac положить файлы в аналогичную структуру:
> `~/.claude/projects/<your-mac-slug>/memory/`. Слаг на Mac будет другой
> (формируется из absolute path), но содержимое то же.

### MEMORY.md (index)

```markdown
- [Always respond in Russian](feedback_language_russian.md) — user's default response language; applies to every conversation in this project
- [Use graphify for architecture/dependency questions](reference_graphify.md) — project has a knowledge graph in `graphify-out/`; query it FIRST before manual exploration
```

### feedback_language_russian.md

```markdown
---
name: Always respond in Russian
description: User's default response language is Russian — applies to all user-facing text in every conversation in this project
type: feedback
originSessionId: 768ee0bf-5d22-4d41-9965-83757f842b0a
---
Always respond to the user in **Russian** by default, regardless of the language of the user's message, code comments, file paths, system prompts, or tool output.

**Why:** User explicitly requested Russian as the default language ("поставь язык по умолчанию русский в настройках клода чтобы ответы были на русском всегда") on 2026-05-05. They expect this to persist across all conversations.

**How to apply:**
- All explanations, plans, status updates, clarifying questions, and end-of-turn summaries → Russian.
- Keep in original language: code, identifiers, file paths, shell commands, tool arguments, direct quotes from logs/errors/files.
- If the user explicitly writes a request in another language and asks for that language back, follow that request — it overrides the default.
- Tried writing the rule to global `~/.claude/CLAUDE.md` first; harness blocked it as self-modification. Memory is the sanctioned channel.
```

### reference_graphify.md

```markdown
---
name: graphify usage rules for this project
description: Strict rules for when to query the knowledge graph, when to update it, and when to fall back to grep/read. Source of truth is the code, not the graph.
type: reference
originSessionId: 768ee0bf-5d22-4d41-9965-83757f842b0a
---
Graphify-сгенерированный knowledge graph живёт в `graphify-out/` (graph.json,
graph.html, GRAPH_REPORT.md, кэш). Это **архитектурная карта верхнего уровня**,
не realtime-снимок кода. Правки, сделанные в текущей сессии, граф ещё не видит —
для них используется обычное чтение файлов.

## Когда использовать `/graphify query`

- **В начале новой сессии** — для загрузки контекста о проекте (модули,
  зависимости, размещение функциональности).
- **Архитектурные / навигационные вопросы**: "где у нас логика X", "какие
  модули зависят от Y", "что будет затронуто если переименовать Z".
- **Перед grep/read** — чтобы сузить область поиска.

## Когда НЕ использовать граф (идти прямо в код)

- Нужны **точные `file:line` ссылки** → grep/read.
- Понимание **логики конкретной функции**, отладка бага → читать сам код.
- **Поведенческий анализ** ("что вернёт функция при условии Y") → читать код.
- **Если первый запрос к графу не дал ответа — не упорствовать**, переходить
  к grep/read. Не делать повторные запросы с переформулировками.

## Когда обновлять граф

Обновление **только по явному триггеру**. Никогда не обновлять в середине
задачи, при каждом сохранении файла, или "на всякий случай".

Триггеры:
1. **post-commit hook** — основной механизм. После каждого `git commit`
   `.git/hooks/post-commit` запускает `graphify update` (incremental).
2. **SessionEnd hook** — если за сессию не было коммита, граф обновляется
   из накопленного контекста сессии (если такой hook сконфигурирован).
3. **Явная команда от пользователя** — "обнови граф", "перестрой граф".
4. **После крупного рефакторинга** (переезд модулей, переименование пакетов,
   изменение точек интеграции) — **запросить у пользователя подтверждение**
   на полный rebuild, не запускать самовольно.

## Режим обновления

- **По умолчанию — incremental** (`graphify update` или `/graphify <path> --update`).
  Пересчитывает только затронутые ноды и рёбра.
- **Полный rebuild** (`/graphify .`) — дорого (~2.4× размера корпуса в токенах).
  Запускать только если: (а) граф явно сломан, (б) после крупного
  архитектурного рефакторинга, (в) по явному запросу пользователя.
- **Ни incremental, ни rebuild — без явного триггера выше.**

## Правила перед `git push`

- **Не коммитить файл графа** (`graph.json`, `graph.html`, `GRAPH_REPORT.md`,
  `manifest.json`, `cost.json` — они в `.gitignore`). Кэш `graphify-out/cache/`
  *можно* коммитить — он ускоряет incremental на новой машине.
- Если post-commit hook не отработал (ошибка/таймаут) — **не блокировать push**,
  сообщить пользователю и предложить запустить обновление вручную.
- Перед push в `master`/`main` — убедиться, что граф отражает финальное
  состояние ветки. После amend / rebase — запустить incremental ещё раз.
- **Граф НЕ часть code review.** Не упоминать его в PR description, если
  только сам PR не про инфраструктуру графа.

## Командная работа (если применимо)

- Локальный post-commit hook — для одиночной работы.
- В команде граф собирается централизованно через CI на push в `main`,
  результат публикуется в shared-локацию. Локальные графы — для скорости
  итерации, "истина" живёт в CI-сборке.
- При расхождении локального и CI-графа — **приоритет CI**.

## Что делать при сбоях

- **Граф не строится / падает** → сообщить пользователю, не пытаться построить
  повторно автоматически.
- **Бессмысленные ноды** (`community_1`, `community_2` на всё подряд) → граф
  плохо подходит к этому корпусу (типично для больших легаси-кодбейсов).
  Сказать пользователю, дальше работать через grep/read, граф не использовать
  до решения.
- **Запросы систематически не находят то, что есть в коде** → предложить
  полный rebuild, **но не запускать без подтверждения**.

## Принцип

Граф — **инструмент навигации, не source of truth**. Source of truth — код в
файлах. Граф устаревает, может быть неполным, может давать ложноположительные
связи. **При любом конфликте между графом и содержимым файлов — верить файлам.**
```

---

## 4. Untracked drafts in repo

Кроме `.claude/settings.local.json` (см. §5) и `graphify-out/` (см. §6), в
рабочем дереве на Windows нет других gitignored/untracked драфтов, относящихся
к проекту. Проверено через `git status --ignored`:

```
.claude/                          # см. §5
.mypy_cache/                      # тулинг
.pytest_cache/                    # тулинг
.ruff_cache/                      # тулинг
graphify-out/.graphify_root       # генерируемое
graphify-out/GRAPH_REPORT.md      # см. §6
graphify-out/cost.json            # генерируемое
graphify-out/graph.html           # генерируемое
graphify-out/graph.json           # генерируемое
graphify-out/manifest.json        # генерируемое
src/**/__pycache__/               # компилированный байт-код
tests/**/__pycache__/             # компилированный байт-код
```

Подкаталога `docs/superpowers/specs/` (упомянутого в README) физически на
Windows-машине **нет** — только `docs/superpowers/plans/`. Если на Mac
`docs/superpowers/specs/` тоже отсутствует — это не баг переноса, его никогда
и не было, README имел в виду этот же `transition-bundle.md` либо ссылался
на `~/.claude/plans/swirling-whistling-tulip.md`.

---

## 5. Claude settings & hooks

### .claude/settings.local.json (в корне репо, gitignored)

```json
{
  "permissions": {
    "allow": [
      "Read(//c/Users/CURSEDEVIL/.claude/**)",
      "Bash(grep -iE \"\\(claude\\\\.md|md$\\)\")",
      "Read(//c/Users/CURSEDEVIL/.claude/plans/**)",
      "Bash(git --version)"
    ]
  }
}
```

> На Mac этот файл **не нужен переносить как есть** — Windows-пути
> бесполезны. Просто создай аналогичный с macOS-путями (или пусть Claude
> сам соберёт permissions по мере работы).

### Глобальные `~/.claude/settings.json` (Windows)

> Релевантных для именно этого проекта секций (хуков/permissions/env)
> в глобальных настройках не обнаружено. Если что-то будет нужно — Claude
> на Mac добавит по запросу через `update-config` skill.

### .git/hooks/post-commit (graphify hook)

```sh
#!/bin/sh
# graphify-hook-start
# Auto-rebuilds the knowledge graph after each commit (code files only, no LLM needed).
# Installed by: graphify hook install

# Skip during rebase/merge/cherry-pick to avoid blocking --continue with unstaged changes
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
[ -d "$GIT_DIR/rebase-merge" ] && exit 0
[ -d "$GIT_DIR/rebase-apply" ] && exit 0
[ -f "$GIT_DIR/MERGE_HEAD" ] && exit 0
[ -f "$GIT_DIR/CHERRY_PICK_HEAD" ] && exit 0

CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only HEAD 2>/dev/null)
if [ -z "$CHANGED" ]; then
    exit 0
fi

# Detect the correct Python interpreter (handles pipx, venv, system installs)
GRAPHIFY_BIN=$(command -v graphify 2>/dev/null)
if [ -n "$GRAPHIFY_BIN" ]; then
    case "$GRAPHIFY_BIN" in
        *.exe) _SHEBANG="" ;;
        *)     _SHEBANG=$(head -1 "$GRAPHIFY_BIN" | sed 's/^#![[:space:]]*//') ;;
    esac
    case "$_SHEBANG" in
        */env\ *) GRAPHIFY_PYTHON="${_SHEBANG#*/env }" ;;
        *)         GRAPHIFY_PYTHON="$_SHEBANG" ;;
    esac
    # Allowlist: only keep characters valid in a filesystem path to prevent
    # injection if the shebang contains shell metacharacters
    case "$GRAPHIFY_PYTHON" in
        *[!a-zA-Z0-9/_.@-]*) GRAPHIFY_PYTHON="" ;;
    esac
    if [ -n "$GRAPHIFY_PYTHON" ] && ! "$GRAPHIFY_PYTHON" -c "import graphify" 2>/dev/null; then
        GRAPHIFY_PYTHON=""
    fi
fi
# Fall back: try python3, then python (Windows has no python3 shim)
if [ -z "$GRAPHIFY_PYTHON" ]; then
    if command -v python3 >/dev/null 2>&1 && python3 -c "import graphify" 2>/dev/null; then
        GRAPHIFY_PYTHON="python3"
    elif command -v python >/dev/null 2>&1 && python -c "import graphify" 2>/dev/null; then
        GRAPHIFY_PYTHON="python"
    else
        exit 0
    fi
fi

export GRAPHIFY_CHANGED="$CHANGED"

# Run rebuild detached so git commit returns immediately.
# Full repo rebuilds can take hours; blocking the post-commit hook stalls the shell.
_GRAPHIFY_LOG="${HOME}/.cache/graphify-rebuild.log"
mkdir -p "$(dirname "$_GRAPHIFY_LOG")"
echo "[graphify hook] launching background rebuild (log: $_GRAPHIFY_LOG)"
nohup $GRAPHIFY_PYTHON -c "
import os, sys
from pathlib import Path

changed_raw = os.environ.get('GRAPHIFY_CHANGED', '')
changed = [Path(f.strip()) for f in changed_raw.strip().splitlines() if f.strip()]

if not changed:
    sys.exit(0)

print(f'[graphify hook] {len(changed)} file(s) changed - rebuilding graph...')

try:
    import os as _os
    from graphify.watch import _rebuild_code
    _force = _os.environ.get('GRAPHIFY_FORCE', '').lower() in ('1', 'true', 'yes')
    _rebuild_code(Path('.'), force=_force)
except Exception as exc:
    print(f'[graphify hook] Rebuild failed: {exc}')
    sys.exit(1)
" > "$_GRAPHIFY_LOG" 2>&1 < /dev/null &
disown 2>/dev/null || true
# graphify-hook-end
```

> **На Mac** — хук ставится одной командой `graphify hook install` (после
> `pip install --user graphifyy`). Этот текст приведён, чтобы было с чем
> сверить, если установщик подведёт.

---

## 6. GRAPH_REPORT.md (snapshot после Foundation milestone)

> Полный отчёт сгенерирован 2026-05-05 от коммита `74afd4fd` (последний
> коммит Foundation). На Mac легко перегенерировать через `graphify update`
> или полный rebuild — но содержимое здесь полезно как сводка структуры.

```
# Graph Report - BOT_CLAWS_YULIIA  (2026-05-05)

## Corpus Check
- 38 files · ~13,429 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 282 nodes · 355 edges · 38 communities (28 shown, 10 thin omitted)
- Extraction: 75% EXTRACTED · 25% INFERRED · 0% AMBIGUOUS · INFERRED: 89 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `session fixture` - 30 edges
2. `ClientRepository` - 19 edges
3. `SettingRepository` - 18 edges
4. `Foundation milestone` - 18 edges
5. `NotifyRuleRepository` - 17 edges
6. `AppointmentRepository` - 15 edges
7. `Client` - 10 edges
8. `WhitelistMiddleware` - 8 edges
9. `Appointment` - 8 edges
10. `load_settings()` - 7 edges

## Hyperedges (group relationships)
- **Bot bootstrap sequence** — config_load_settings, main_configure_logging, config_ensure_data_dir, main_seed_defaults, main_build_dispatcher, main_run [EXTRACTED 1.00]
- **Repository pattern with session-based ORM access** — appointments_AppointmentRepository, clients_ClientRepository, notify_rules_NotifyRuleRepository, settings_SettingRepository [INFERRED 0.95]
- **SQLAlchemy model inheritance from Base** — models_Setting, models_Client, models_Appointment, models_NotifyRule, models_ScheduledJob [EXTRACTED 1.00]
- **Foundation Implementation Tasks 1-18** — 18 sequential plan tasks [EXTRACTED 1.00]

## Knowledge Gaps (на момент Foundation)
- 96 isolated node(s) с ≤1 connection — типично для greenfield-проекта
  без кросс-модульной интеграции (handlers/keyboards ещё не зашиты в
  бизнес-сервисы).
- 10 thin communities (<3 nodes) — уйдут как только появятся Booking core
  и Notifications.
```

> Полный отчёт (с подробным разбиением по communities) — в
> `graphify-out/GRAPH_REPORT.md` после первого `graphify update` на Mac.

---

## 7. Chat knowledge dump (Booking core / Notifications / Voice / Deploy)

> **Important:** спецификация в §1 является исчерпывающим dump'ом всех
> архитектурных решений по этим темам. Она писалась как итог обсуждения
> и содержит все ответы на вопросы, поднятые в transition-запросе.
> Ниже — карта "куда смотреть в спеке за каждым решением" + явные пробелы.

### Booking core decisions → §1

| Вопрос | Ответ в спеке |
|---|---|
| Формат `/add` | "Поток C — Текстовая команда": `/add 2026-05-06 14:30 Олег @oleg_insta маникюр`. Жёсткий regex через `text_parser`, fallback на LLM при нераспарсе. |
| FSM-wizard шаги | "Поток B — FSM-форма": Шаг 1 (клиент: список+поиск+«Новый») → Шаг 2 (когда: гибрид) → Шаг 3 (время: сетка 30-мин с «Другое») → Шаг 4 (заметка: опционально) → Шаг 5 (конфликт-чек) → Шаг 6 (финальная карточка). |
| "Гибридный" выбор даты/времени | Шаг 2: кнопки `[Сегодня][Завтра][Послезавтра][📅 Календарь][⌨️ Текстом]`. Календарь — собственная inline-сетка месяца. «Текстом» — свободный ввод → text_parser → fallback LLM. |
| Обработка конфликтов | Шаг 5: если в `(starts_at, starts_at + duration)` уже есть scheduled-запись — диалог `⚠️ В это время Олег с 14:00 до 15:00. Записать всё равно? [Записать] [Изменить время] [Отмена]`. Длительность 60 мин жёстко, **не показывается** пользователю в UI. |
| `/today`, `/tomorrow`, `/week` формат | Файл `bot/handlers/lists.py` (см. структуру в §1). Формат вывода в спеке детально не зафиксирован — это решение оставлено на момент имплементации Plan #2. Базовая идея: список записей с временем + именем + кнопками карточки. |
| История клиента | Файл `bot/handlers/clients.py` — `/clients` + карточка + история. CallbackData: `ClientCD(action="history", client_id=…)`. Конкретный layout — на момент Plan #2. |

### Notifications decisions → §1

| Вопрос | Ответ в спеке |
|---|---|
| Что значит preset `eve_morning` | Дефолтный пресет = два правила в `notify_rules`: `time_day_before=20:00 enabled` + `time_same_day=09:00 enabled`. Это **не один template** — это два независимых рула, которые при срабатывании дают **сводный дайджест** на день. |
| UI настройки правил | `/settings → 🔔 Уведомления → ⚙️ Своя настройка` — список правил с toggles, кнопка `[+ Добавить своё]` запускает мини-FSM (тип → значение → сохранение). При смене пресета — диалог про затирание кастомных правил с тремя опциями. |
| Сводный дайджест в 09:00 | `morning_digest` собирает **все** записи дня (`scheduled` со `starts_at` в текущей дате owner_tz) и шлёт ОДНО сообщение. Дедупликация: если на тот же `fire_at` уже запланирован дайджест — не плодим. Recovery на старте: если `fire_at < NOW() − 6h` пропускаем, иначе шлём с `⏰ (с задержкой)`. |

### Voice intake decisions → §1

| Вопрос | Ответ в спеке |
|---|---|
| Промпт для GPT-4o-mini | Контекст в input: распознанный текст + текущая дата/время в Asia/Almaty + список существующих клиентов (id+name+instagram) для матчинга. Конкретный текст промпта в спеке не зафиксирован — будет написан в Plan #4. |
| Структура output JSON | `{client_name, client_id_guess, starts_at_iso, instagram, visit_note, confidence}` (`confidence` — 0..1). Если `client_id_guess` есть — привязка к существующему клиенту. |
| Ambiguity / неполные данные | `confidence < 0.7` ИЛИ отсутствуют обязательные поля → **минуем карточку-подтверждение**, открываем FSM-форму с предзаполненными полями. Никаких многоступенчатых уточнений в чате. |

### Deploy decisions → §1

| Вопрос | Ответ в спеке |
|---|---|
| Куда планируется деплой | **Oracle Cloud Free VM** (Linux, 24/7). Не Fly.io, не Railway, не своя машина. См. секцию "Деплой (Oracle Cloud Free)". |
| Запуск | Multi-stage Dockerfile + docker-compose (bot + redis) + systemd unit `/etc/systemd/system/bot-claws.service` (`systemctl enable --now bot-claws.service`). На рестарт VM — авто-старт. |
| **Бэкап SQLite — в спеке НЕ закрыт.** | В спеке только `volumes: ./data:/data` для персистентности. Конкретная стратегия резервного копирования (cron + `sqlite3 .backup`, rsync на внешний сторадж, S3 — что-то ещё) обсуждалась в чатах поверхностно и НЕ дошла до фиксации. **Это open item для Plan #5 — Deploy.** |

### Discarded options + reasons

В спеке нет явной секции "rejected alternatives", потому что она писалась
сразу как утверждённый итог. Из явных решений, где можно реконструировать
отказы:

- **STT: одна реализация → отвергнута** в пользу dual-provider (OpenAI + Yandex).
  Причина: Yandex — fallback при недоступности OpenAI или при долгих аудио,
  плюс возможность работать без выезда трафика за границу.
- **Длительность визита: показывать пользователю при создании → отвергнута**.
  Причина: визуальный шум, мастер всё равно знает, что один визит = ~60 мин.
  Длительность остаётся как служебная для конфликт-чекера.
- **Хранилище FSM: in-memory → отвергнуто** в пользу Redis с TTL. Причина:
  необходимость переживать рестарты бота (см. recovery-flow в спеке).
- **Хостинг: своя машина / VPS → отвергнут** в пользу Oracle Cloud Free.
  Причина: бесплатно, 24/7, достаточно ресурсов для single-user бота.
- **Уведомления: per-appointment job → отвергнут** в пользу дедупликации
  дайджестов на тот же `fire_at`. Причина: при 5+ записях в день не хочется
  получать 5+ отдельных пингов в 20:00 и 09:00 — нужен один сводный.

Дополнительные обсуждения, которые НЕ дошли до фиксации в спеке и для
которых стоит явно спросить пользователя при возобновлении работы:

1. **Стратегия бэкапа SQLite** на Oracle Cloud (см. выше).
2. **Часовой пояс DST**: Asia/Almaty — без перехода на летнее время с 2005 г.,
   поэтому DST-edge-cases формально не применимы, но тесты `notifications/rules`
   всё равно перечислены в спеке как "DST, переходы суток" — общий шаблон.
3. **i18n даты в карточке-подтверждении** (`6 мая (вт)`) — формат русский,
   жёстко зашит. Если бот когда-нибудь будет multi-user — это придётся
   перерабатывать.
4. **Лимиты OpenAI/Yandex** — graceful-degradation при rate-limit'е в спеке
   не описан. Сейчас implicit: пробросить ошибку в global error-handler →
   "⚠️ Что-то пошло не так".

---

## NOT FOUND

- Дополнительных планов для проекта в `~/.claude/plans/` нет (кроме самой спеки).
- Подкаталога `docs/superpowers/specs/` в репо нет — README ссылается, но
  физически он отсутствует с момента создания репозитория.
- Сессионные `.jsonl`-логи (2.6 МБ + 0.3 МБ) **не включены** — формат сырой,
  большую часть архитектурных решений уже впитала спека. При необходимости
  глубокого восстановления контекста — оба файла лежат локально на Windows-машине
  по пути `~/.claude/projects/e--BOT-CLAWS-YULIIA/*.jsonl` и могут быть
  переданы отдельно по запросу.
