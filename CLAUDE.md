# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Global rules (`~/.claude/CLAUDE.md`) and user instructions take precedence over
anything below.

---

## First-time setup walkthrough (proactive, do NOT wait to be asked)

On the **first session** in this repo on a new machine, before doing anything
else, check whether the project is set up locally. **If any of these is missing,
proactively offer the setup walkthrough as your first message** — don't wait for
the user to ask:

| Check | Command | If missing → flag |
|---|---|---|
| `.env` exists | `test -f .env` | needs `cp .env.example .env` + filling secrets |
| Poetry installed | `poetry --version` | needs install via `curl -sSL https://install.python-poetry.org \| python3 -` |
| Python deps installed | `test -d .venv` | needs `poetry install` |
| Docker available | `docker --version` | needs Docker Desktop |
| Git hooks installed | `test -f .git/hooks/post-commit` | needs `graphify hook install` |

**Detection signal:** if `.env` is absent, treat the repo as freshly cloned
and run the full walkthrough below proactively. Do this **once** — once `.env`
exists, don't repeat unless the user asks again.

### Walkthrough message to deliver (Russian)

```
Похоже, ты только что склонировал проект. Прогоню сразу полный setup-чеклист.

1. Установить инструменты:
   • Homebrew (если ещё нет): /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   • brew install python@3.12 git gh
   • brew install --cask docker  ← открой Docker.app один раз вручную
   • curl -sSL https://install.python-poetry.org | python3 -
   • poetry config virtualenvs.in-project true

2. .env (НЕ берётся из git — заполнить заново):
   • cp .env.example .env
   • Заполни BOT_TOKEN, OWNER_CHAT_ID, OPENAI_API_KEY (или sk-test пока voice
     не реализован).

3. Зависимости:
   • poetry install

4. Sanity-check:
   • poetry run pytest -v          # ожидается: 39 passed
   • poetry run ruff check src tests
   • poetry run mypy src

5. Установка graphify-хука (для авто-обновления графа после каждого commit'а):
   • pip install --user graphifyy   # если ещё нет
   • cd <repo> && graphify hook install

6. Запуск через Docker:
   • docker compose up --build

После 6 — пиши боту /start в Telegram. Что хочешь дальше?
```

После прохождения walkthrough — следующий вопрос пользователя обрабатывать как обычно.

---

## Common commands

Run from repo root. The local virtualenv is `.venv/` (`virtualenvs.in-project = true`).

```bash
# Install / update dependencies
poetry install

# Tests
poetry run pytest -v                                          # full suite (39 passing)
poetry run pytest tests/storage/test_repositories.py -v       # single file
poetry run pytest tests/storage/test_repositories.py::TestClientRepository::test_create_client -v   # single test
poetry run pytest -k whitelist                                # filter by keyword
poetry run pytest --cov=src --cov-report=term-missing         # with coverage

# Lint + type check (must be clean before commit)
poetry run ruff check src tests
poetry run ruff check --fix src tests        # autofix
poetry run mypy src                          # strict mode (see pyproject.toml)

# Alembic (migrations live in src/storage/migrations/versions)
mkdir -p data
DB_PATH="$(pwd)/data/bot.db" poetry run alembic upgrade head
DB_PATH="$(pwd)/data/bot.db" poetry run alembic revision --autogenerate -m "<desc>"
DB_PATH="$(pwd)/data/bot.db" poetry run alembic downgrade -1

# Run the bot — needs Redis, easiest path is docker compose
docker compose up --build                    # builds image, applies migrations, starts polling
docker compose logs -f bot                   # tail bot logs
docker compose down                          # stop (data/ + redis-data/ persist on disk)
```

There is **no** `make` / `npm` / unified task runner — invoke `poetry run` directly.

---

## Architecture

Three-layer design with a strict dependency direction (`bot → services → storage`).
Cross-layer imports going the other way are forbidden.

### `src/bot/` — presentation (aiogram 3)
Handlers, keyboards, FSM states, middlewares. Knows about Telegram primitives
(`Message`, `CallbackQuery`, `FSMContext`); does **not** import SQLAlchemy directly.
Routers are wired in `src/main.py` → `_build_dispatcher`. The
`WhitelistMiddleware` is registered as **`outer_middleware` before any router**,
so unauthorised updates are dropped before any handler logic — silently, by
design (no reply to non-owner). It walks every payload type in `aiogram.types.Update`
to find a `from_user.id` and compares to `OWNER_CHAT_ID`.

### `src/services/` — domain logic
No aiogram imports. Each module exposes async functions that take an
`AsyncSession` and return plain values or ORM instances. Example:
`settings_service.seed_defaults(session)` is idempotent and called once at
startup. Future skeletons live in `services/parser/`, `services/voice/`,
`services/notifications/` (Plans #2–#5).

### `src/storage/` — persistence (SQLAlchemy 2.0 async)
- `models.py` — five tables: `settings`, `clients`, `appointments`,
  `notify_rules`, `scheduled_jobs`. Models are **dumb schema only**; no methods,
  no validation, no business logic.
- `repositories/` — one repository per model
  (`settings.py`, `clients.py`, `appointments.py`, `notify_rules.py`).
  Repositories take an `AsyncSession` in `__init__` and own all queries.
  Service-layer code goes through repositories, never raw `select()`.
- `db.py` — `create_engine`, `create_session_factory`, and `session_scope`
  (async context manager: commit on success, rollback on exception). Thin
  plumbing — no business logic.
- `migrations/` — Alembic. `env.py` reads `DB_PATH` from the environment and
  binds to `Base.metadata`. Migrations run in the docker-compose entrypoint
  (`alembic upgrade head && python -m src.main`), **not** inside `main.py`.

### Bootstrap (`src/main.py`)
Strict order: load settings → configure logging → ensure data dir → seed
defaults (opens its own short-lived engine and disposes it) → build dispatcher
with Redis FSM storage (TTL = `FSM_TTL_MINUTES`) + whitelist + routers →
`start_polling`. Migrations are not run here.

### Config (`src/config.py`)
`pydantic-settings` `Settings` class — single source of truth for env vars.
The `model_validator` enforces that the chosen `STT_PROVIDER` has its required
keys (so the bot fails fast on bad `.env`), and that an LLM key is available
(`LLM_API_KEY` falls back to `OPENAI_API_KEY` via `effective_llm_key`). **Do
not read env vars directly anywhere else** — accept a `Settings` (or specific
fields) as an argument.

### State / persistence
- **SQLite** (`/data/bot.db` in container, `./data/bot.db` locally) — domain
  data. Mounted as a volume in docker-compose so it survives rebuilds.
- **Redis 7** — aiogram FSM storage only. Configured with AOF + a snapshot
  every 60s so an in-progress wizard survives a restart. URL is
  `redis://redis:6379/0` inside compose, override `REDIS_URL` for local dev.

### Tests
- `pytest-asyncio` in `auto` mode (configured in `pyproject.toml`); no need
  for `@pytest.mark.asyncio` decorators.
- `tests/conftest.py` provides two fixtures used everywhere:
  `engine` (in-memory SQLite + `Base.metadata.create_all`) and `session`
  (an `AsyncSession` against that engine).
- A module-level `event.listens_for(Engine, "connect")` hook in `conftest.py`
  enables `PRAGMA foreign_keys=ON` for **every** SQLite connection opened during
  tests. If you build an engine outside the fixtures, FK enforcement is on too —
  rely on cascade deletes accordingly.
- Tests for the bot layer exercise middleware/router objects directly; they do
  not open a real Telegram connection.

---

## Knowledge Graph (graphify)

Граф знаний проекта — архитектурная карта верхнего уровня, **не realtime
состояние кода**. Текущие правки Claude видит через обычное чтение файлов,
для этого граф не нужен.

### Когда использовать `/graphify query`

- В начале новой сессии — для загрузки контекста о проекте.
- Архитектурные и навигационные вопросы: зависимости между модулями,
  размещение функциональности, точки интеграции, "где у нас логика X".
- Перед grep/read — чтобы сузить область поиска.

### Когда НЕ использовать граф (идти сразу в код)

- Точные `file:line` ссылки нужны → grep/read.
- Понимание логики конкретной функции, отладка бага → читать сам код.
- Поведенческий анализ (что вернёт функция при условии Y) → читать код.
- Если первый запрос к графу не дал ответа — не упорствовать,
  переходить к grep/read, не делать повторные запросы с переформулировками.

### Когда обновлять граф

Обновление запускается ТОЛЬКО по явному триггеру. Никогда не обновлять
в середине задачи, при каждом сохранении файла, или "на всякий случай".

Триггеры обновления:
1. **post-commit hook** — основной механизм. После каждого `git commit`
   запускается `graphify update` (incremental). Настроено в
   `.git/hooks/post-commit`.
2. **SessionEnd hook** — если за сессию не было коммита, граф обновляется
   из накопленного контекста сессии.
3. **Явная команда от пользователя** — "обнови граф", "перестрой граф".
4. **После крупного рефакторинга**, который меняет архитектуру (переезд
   модулей, переименование пакетов, изменение точек интеграции) —
   запросить у пользователя подтверждение на полный rebuild.

### Режим обновления

- По умолчанию — **incremental update** (`graphify update`), пересчитывает
  только затронутые ноды и рёбра.
- Полный rebuild (`/graphify .`) — дорого (~2.4× размера корпуса в
  токенах). Запускать только когда: (а) граф явно сломан, (б) после
  крупного архитектурного рефакторинга, (в) по явному запросу пользователя.
- Не запускать ни incremental, ни rebuild без явного триггера выше.

### Правила перед `git push`

- Не коммитить файл графа (`graph.json` или аналог) — он генерируемый,
  должен быть в `.gitignore`. Кэш `graphify-out/cache/` *можно* коммитить.
- Если post-commit hook не отработал (ошибка, таймаут) — не блокировать
  push, сообщить пользователю об этом и предложить запустить обновление вручную.
- Перед push в основную ветку (`main`/`master`) — убедиться, что граф
  отражает финальное состояние ветки. Если были amend-коммиты или
  rebase — запустить incremental update ещё раз.
- Граф НЕ является частью code review. Не упоминать его в PR description,
  если только сам PR не про инфраструктуру графа.

### Командная работа (если применимо)

- Локальный post-commit hook — для одиночной работы.
- В команде граф собирается централизованно через CI на push в `main`,
  результат публикуется в shared-локацию. Локальные графы у каждого
  разработчика — для скорости итерации, "истина" живёт в CI-сборке.
- При расхождении локального и CI-графа — приоритет у CI.

### Что делать при сбоях

- Граф не строится / падает с ошибкой → сообщить пользователю, не пытаться
  построить повторно автоматически.
- Граф выдаёт бессмысленные ноды (`community_1`, `community_2` на всё
  подряд) → это значит, что граф плохо подходит под этот корпус
  (типично для больших легаси-кодбейсов). Сказать об этом, дальше
  работать через grep/read, граф не использовать до решения.
- Запросы к графу систематически не находят то, что есть в коде →
  предложить полный rebuild, но не запускать без подтверждения.

### Принцип

Граф — инструмент навигации, **не source of truth**. Source of truth — это
код в файлах. Граф устаревает, граф может быть неполным, граф может
давать ложноположительные связи. **При любом конфликте между графом и
содержимым файлов — верить файлам.**

---

## Project conventions (specific to BOT_CLAWS_YULIIA)

- **Язык ответов** — русский по умолчанию. Код, идентификаторы, команды,
  пути файлов и цитаты из логов остаются на языке оригинала.
- **Минимальный Python** — 3.10 для локальной разработки, 3.12 в проде через
  `Dockerfile`. Не использовать фичи строго `3.11+` (например `Self` из
  typing) — они сломают локальный dev на Mac/Windows с 3.10.
- **Тестирование** — TDD (failing test → impl → pass → commit). pytest-asyncio.
  In-memory SQLite в фикстурах `engine`/`session` (`tests/conftest.py`).
- **Git** — `core.autocrlf=false`, `core.eol=lf`. Никогда не коммитить
  `.env`, `data/`, `*.db`, `*.log`, Redis dumps, generated graph artifacts.
- **Линтинг** — `poetry run ruff check src tests` должен быть clean перед
  каждым коммитом. `RUF001-003` (Cyrillic chars) намеренно в ignore.
- **Mypy strict** — `poetry run mypy src` должен быть clean.
- **Архитектура** — слои `bot/` (presentation, aiogram), `services/`
  (доменная логика, ничего про aiogram), `storage/` (SQLAlchemy + repos +
  alembic). Repository-pattern над моделями. Whitelist через
  `WhitelistMiddleware` принимает множество chat ID — `OWNER_CHAT_ID`
  (мастер) + `ADMIN_CHAT_IDS` (доп. админы, например разработчик).
- **Полная спецификация** — на машине пользователя в
  `~/.claude/plans/swirling-whistling-tulip.md`. Подробные планы реализации
  лежат в `docs/superpowers/plans/`.

## Состояние проекта (актуальное)

Все 7 фаз спецификации закрыты, бот в продакшене. История по веткам:

| Фаза | План | Статус |
|---|---|---|
| 1 | Foundation — скелет, репозитории, миграции, тесты | ✅ done |
| 2 | Booking core — FSM-мастер, CRUD записей, конфликт-чек | ✅ done |
| 3 | Notifications — APScheduler, recovery, /settings | ✅ done |
| 4 | Voice intake — STT + LLM + Action registry | ✅ done |
| 5 | Voice intake edit + accuracy — per-field редактор + few-shot | ✅ done |
| 6 | Smart fallback — Layer A action tolerance + второй мозг | ✅ done |
| 7 | Deploy — Oracle Cloud, Docker, systemd, бэкапы | ✅ done |

**Production:** Oracle Cloud E2.1.Micro VM (`134.98.142.61`), Ubuntu 20.04
Minimal, docker compose stack под systemd, weekly backup в Telegram.
Подробности и операционные команды — в auto-memory `project_deploy.md`.

**Дальнейшая работа** — только по запросу пользователя (новые фичи,
UX-доработки, баги от мастера в реальной эксплуатации).
