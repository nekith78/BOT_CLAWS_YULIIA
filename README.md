# BOT_CLAWS_YULIIA

Личный Telegram-бот для учёта записей клиентов с голосовым вводом, гибкими
уведомлениями и хранилищем в SQLite. Один пользователь (whitelist по chat_id).

## Текущий статус

🏗️ **Foundation milestone завершён** (15 коммитов на ветке `plan/foundation`).
Бот стартует, отвечает на `/start` главным меню, БД с пятью таблицами и
дефолтным сидом, whitelist режет чужих. Дальше — Booking core, Notifications,
Voice intake, Deploy (см. `docs/superpowers/plans/`).

## Стек

- Python 3.10+ для разработки (3.12 в проде через Docker)
- aiogram 3
- SQLAlchemy 2.0 (async) + aiosqlite + Alembic
- Redis 7 (FSM-storage с TTL и восстановлением прерванных flow)
- APScheduler (планирование уведомлений) — *появится в Plan №4*
- OpenAI Whisper (default) / Yandex SpeechKit — *появится в Plan №5*
- GPT-4o-mini — *появится в Plan №5*

## Возможности (по итогам всех планов)

- **Голосом**: записываешь "запиши Олега завтра в два часа дня" — бот
  расшифровывает, парсит и присылает карточку с подтверждением.
- **Формой**: пошаговый wizard с гибридным выбором даты/времени.
- **Командой**: `/add 2026-05-06 14:30 Олег @oleg_insta маникюр`.
- Списки `/today`, `/tomorrow`, `/week`, история по клиенту.
- Уведомления: дефолт — 20:00 накануне + 09:00 утром (сводный дайджест).
  Гибкая настройка через UI бота.

---

## Запуск на Mac (после клонирования с GitHub)

Если ты только что склонировал проект с GitHub на свой Mac, выполни эти шаги
**ровно по порядку**:

### 1. Поставить инструменты разработки

```bash
# Homebrew (если ещё нет)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Python 3.10+ (на Sonoma+ обычно уже есть; иначе:)
brew install python@3.12

# Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Docker Desktop для Mac (apple silicon: Apple chip / Intel: Intel chip)
brew install --cask docker
# Открой Docker Desktop вручную хотя бы раз, чтобы он стартанул демон.

# Git (обычно уже есть; иначе:)
brew install git

# GitHub CLI (опционально, для удобной работы с репо)
brew install gh
```

### 2. Создать `.env` (НЕ берётся из git — заполнить заново)

```bash
cd ~/path/to/BOT_CLAWS_YULIIA   # или туда, куда клонировал
cp .env.example .env
```

Открой `.env` и заполни:
- `BOT_TOKEN` — токен от @BotFather (можно тестового бота создать отдельно)
- `OWNER_CHAT_ID` — твой Telegram user id (узнать через @userinfobot)
- `OPENAI_API_KEY` — реальный ключ OpenAI (или тестовая строка `sk-test`,
  пока Voice intake не реализован)
- Остальное оставить по умолчанию

### 3. Установить Python-зависимости

```bash
poetry config virtualenvs.in-project true
poetry install
```

### 4. Прогнать тесты

```bash
poetry run pytest -v
poetry run ruff check src tests
poetry run mypy src
```

Должно быть: **39 passed**, ruff clean, mypy clean.

### 5. Запустить миграцию локально (sanity-check)

```bash
mkdir -p data
DB_PATH="$(pwd)/data/bot.db" poetry run alembic upgrade head
```

Должна примениться миграция `0001_initial`.

### 6. Запустить бот через Docker

Убедись что Docker Desktop запущен (значок в menu bar).

```bash
docker compose up --build
```

В логах: `Starting bot, owner=<id> tz=Asia/Almaty stt=openai`,
затем `Run polling for bot @<your_bot>`.

### 7. Проверить в Telegram

- Напиши боту `/start` — он ответит "Привет, …!" и покажет главное меню.
- С чужого аккаунта `/start` — бот молчит, в логах `unauthorized access attempt`.

### 8. Продолжить разработку

Текущая ветка: `plan/foundation` уже смерджена в `master` (или `main`).
Следующий шаг — **Plan №2 (Booking core)**, лежит в
`docs/superpowers/plans/` (или будет создан в новом сеансе с Claude).

---

## Запуск на Windows (для исторической справки — отсюда был перенос)

```powershell
# Установить Python 3.10+ с python.org (с галочкой "Add to PATH")
pip install --user poetry
poetry config virtualenvs.in-project true
poetry install
poetry run pytest -v
```

Использовался **Git Bash** для запуска bash-команд из планов.

---

## Безопасность и приватность

- Никаких секретов в коде — только в `.env` (в `.gitignore`).
- БД и логи тоже в `.gitignore` — могут содержать персональные данные клиентов.
- Whitelist-middleware пропускает только `OWNER_CHAT_ID`.
- Бот падает на старте, если обязательные ключи не заданы.
- Перед `git push`: `git status` не должен показывать `.env`, `data/`, `*.db`,
  `*.log`, `dump.rdb`.

## Структура

```
src/
├── bot/                   aiogram-хендлеры, клавиатуры, FSM, middleware
│   ├── handlers/          handlers (пока только start.py)
│   ├── keyboards/         main_menu.py
│   └── middlewares/       whitelist.py
├── services/              доменная логика
│   └── settings_service.py  TZ/preset/duration helpers + idempotent seed
├── storage/               SQLAlchemy-модели и миграции
│   ├── models.py          5 моделей: Setting, Client, Appointment, NotifyRule, ScheduledJob
│   ├── repositories/      4 репозитория (один на модель)
│   ├── db.py              async engine + session_scope
│   └── migrations/        alembic
├── config.py              pydantic-settings (валидация на старте)
└── main.py                bootstrap

tests/                     pytest-asyncio, in-memory SQLite, 39 тестов

docs/
├── superpowers/
│   ├── specs/             спецификации (брейншторм)
│   └── plans/             пошаговые планы реализации
graphify-out/             graphify-сгенерированный knowledge graph
├── graph.html            интерактивный граф — открой в браузере
├── graph.json            raw данные графа (для запросов)
├── GRAPH_REPORT.md       аудит-отчёт + сообщества + god nodes
├── cache/                кэш semantic extraction (для /graphify --update)
├── manifest.json         список файлов на момент последней генерации
└── cost.json             счётчик токенов LLM (для этого корпуса 0 — был AST-only)

C:\Users\<user>\.claude\plans\swirling-whistling-tulip.md
   полная спецификация всего проекта (на Windows)
```

## Граф проекта (graphify)

В `graphify-out/` лежит сгенерированный knowledge-граф структуры кода, кластеров
модулей и зависимостей. Открой `graphify-out/index.html` в браузере.

При архитектурных вопросах в Claude Code предпочитай команду `/graphify query
<вопрос>` вместо ручного grep'а — граф видит транзитивные зависимости.
Регенерация при крупных рефакторах: `/graphify` (без аргументов) на корне репо.
