# Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Поднять бота на проверяемой основе: рабочий запуск через `docker compose up`, ответ на `/start` главным меню, инициализированная БД с пятью таблицами, дефолтный seed настроек, whitelist-защита от чужих пользователей.

**Architecture:** SQLAlchemy 2.0 async + aiosqlite + Alembic для хранения. Repository-pattern поверх моделей. Whitelist реализуется как aiogram-middleware на уровне Dispatcher (применяется ко всем апдейтам до route'инга). `/start` отдаёт reply-keyboard-меню. `main.py` собирает всё вместе.

**Tech Stack:** Python 3.12, aiogram 3, SQLAlchemy 2.0 (async), aiosqlite, Alembic, Redis 7 (FSM-storage), pydantic-settings, pytest + pytest-asyncio.

**Shell:** Все команды ниже даны в bash-стиле. Платформа разработки — Windows 11
+ PowerShell. Самый простой способ — открыть **Git Bash** (ставится с Git for
Windows), он понимает `mkdir -p`, `rm -f`, `mv`, `cp`, `VAR=val cmd`. Если
работаешь из PowerShell, эквиваленты:

| bash | PowerShell |
|---|---|
| `mkdir -p data` | `New-Item -ItemType Directory -Force data` |
| `rm -f data/bot.db` | `Remove-Item -Force -ErrorAction SilentlyContinue data/bot.db` |
| `mv a b` | `Move-Item a b` (или `git mv a b` если файл уже отслеживается) |
| `cp a b` | `Copy-Item a b` |
| `DB_PATH=data/bot.db cmd` | `$env:DB_PATH="data/bot.db"; cmd` |
| `$(pwd)/data/bot.db` | `"$pwd/data/bot.db"` |

**Prerequisites:**
- Скаффолд этапа 1 уже создан (см. `e:\BOT_CLAWS_YULIIA`):
  файлы [.gitignore](../../../.gitignore), [.env.example](../../../.env.example),
  [pyproject.toml](../../../pyproject.toml), [Dockerfile](../../../Dockerfile),
  [docker-compose.yml](../../../docker-compose.yml), [alembic.ini](../../../alembic.ini),
  [src/config.py](../../../src/config.py), [src/main.py](../../../src/main.py),
  пустые `__init__.py` для пакетов, [tests/test_smoke.py](../../../tests/test_smoke.py).
- Git **не инициализирован** — Task 1 это исправляет.
- `poetry install` ещё не выполнялся — это можно сделать локально для запуска тестов; в Docker — выполняется автоматически при `docker compose build`.

---

## File Structure

Файлы, создаваемые / изменяемые в этом плане:

| Путь | Назначение |
|---|---|
| `src/storage/db.py` | Async engine, session_factory, контекст-менеджер для сессий |
| `src/storage/models.py` | `Base`, `Setting`, `Client`, `Appointment`, `NotifyRule`, `ScheduledJob` |
| `src/storage/repositories/__init__.py` | Re-exports |
| `src/storage/repositories/clients.py` | `ClientRepository` |
| `src/storage/repositories/appointments.py` | `AppointmentRepository` (включая overlap-query) |
| `src/storage/repositories/notify_rules.py` | `NotifyRuleRepository` |
| `src/storage/repositories/settings.py` | `SettingRepository` (typed get/set) |
| `src/storage/migrations/env.py` | _Изменяется_ — импорт `Base.metadata` |
| `src/storage/migrations/versions/0001_initial.py` | Первая миграция, создаёт все 5 таблиц |
| `src/services/settings_service.py` | Высокоуровневый API: TZ, preset, default_duration, dual-write seed на старте |
| `src/bot/middlewares/whitelist.py` | `WhitelistMiddleware` |
| `src/bot/keyboards/main_menu.py` | `main_menu_kb()` (reply keyboard) |
| `src/bot/handlers/start.py` | Router + `/start` handler |
| `src/main.py` | _Изменяется_ — регистрация middleware и router'ов |
| `tests/storage/__init__.py` | empty |
| `tests/storage/test_models.py` | smoke-тесты на CRUD моделей |
| `tests/storage/test_repositories.py` | тесты репозиториев (overlap, search, seed) |
| `tests/services/__init__.py` | empty |
| `tests/services/test_settings_service.py` | тесты seed и getters |
| `tests/bot/__init__.py` | empty |
| `tests/bot/test_whitelist_middleware.py` | тест middleware |
| `tests/bot/test_start_handler.py` | тест /start handler |
| `tests/conftest.py` | _Изменяется_ — добавляются fixtures для in-memory DB |

**Принцип:** один файл = одна ответственность. Каждый репозиторий — отдельный
файл, чтобы не плодить класс-помойку. Тесты лежат рядом по структуре `src/`.

---

## Tasks

### Task 1: Initialize git and commit scaffold

**Files:**
- Create: `e:/BOT_CLAWS_YULIIA/.git/*` (через `git init`)

- [ ] **Step 1: Init git**

```bash
cd e:/BOT_CLAWS_YULIIA
git init
git config core.autocrlf false   # сохраняем LF
git config core.eol lf
```

- [ ] **Step 2: Verify .gitignore покрывает секреты ДО первого add**

```bash
git status --ignored -s | head -40
```

Expected: видим `!! .env.example` (не игнорится — нужен в репо), но `.env` (если случайно создан) — в ignored. `data/`, `__pycache__/` — игнорятся. **Если `.env` показан как untracked — STOP и убедиться что .gitignore работает.**

- [ ] **Step 3: Stage scaffold files (без секретов)**

```bash
git add .gitignore .env.example pyproject.toml Dockerfile docker-compose.yml alembic.ini README.md
git add src/ tests/ docs/
git status -s
```

Expected: только перечисленные файлы в staging, никаких `.env`, `data/`, `*.db`, `*.log`.

- [ ] **Step 4: Initial commit**

```bash
git commit -m "chore: initial scaffold with config, dockerfile, alembic"
```

Expected: один коммит, hash зафиксирован.

- [ ] **Step 5: Создать ветку для Foundation**

```bash
git checkout -b plan/foundation
```

---

### Task 2: SQLAlchemy Base, async engine, session helpers

**Files:**
- Create: `src/storage/db.py`
- Test: `tests/storage/__init__.py` (empty), `tests/conftest.py` _(изменяется)_

- [ ] **Step 1: Создать пустой `tests/storage/__init__.py`**

```python
```

(пустой файл — разрешает pytest импортировать `tests.storage.*`)

- [ ] **Step 2: Расширить `tests/conftest.py` фикстурой in-memory DB**

Полностью заменить содержимое:

```python
"""Pytest fixtures."""

from __future__ import annotations

from typing import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.storage.models import Base


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
```

- [ ] **Step 3: Написать failing test для `db.py`**

Создать `tests/storage/test_db.py`:

```python
"""Verify async engine + session factory build correctly."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage import db


@pytest.mark.asyncio
async def test_create_engine_and_run_query() -> None:
    engine = db.create_engine("sqlite+aiosqlite:///:memory:")
    factory = db.create_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_session_scope_commits_on_exit() -> None:
    engine = db.create_engine("sqlite+aiosqlite:///:memory:")
    factory = db.create_session_factory(engine)
    async with db.session_scope(factory) as session:
        await session.execute(text("CREATE TABLE t (id INTEGER)"))
        await session.execute(text("INSERT INTO t VALUES (42)"))

    async with factory() as verify:
        result = await verify.execute(text("SELECT id FROM t"))
        assert result.scalar() == 42
    await engine.dispose()
```

- [ ] **Step 4: Запустить тест — должен упасть**

```bash
poetry run pytest tests/storage/test_db.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.storage.db'` или `AttributeError`.

- [ ] **Step 5: Реализовать `src/storage/db.py`**

```python
"""Async SQLAlchemy engine, session factory, and a transaction-scoped helper.

Keep this module thin — repositories live elsewhere; this is just plumbing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(db_url: str, *, echo: bool = False) -> AsyncEngine:
    """Build an async engine. SQLite gets check_same_thread=False via the URL handler."""
    return create_async_engine(db_url, echo=echo, future=True)


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open a session, commit on success, rollback on exception."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

- [ ] **Step 6: Запустить тест — должен пройти**

```bash
poetry run pytest tests/storage/test_db.py -v
```

Expected: 2 passed. (Тест ссылается на `Base` из `models.py`, который ещё не создан в conftest, но наш test_db.py не импортирует Base напрямую — должно пройти.)

⚠️ Если падает на импорте `from src.storage.models import Base` в conftest — пропустить пока, написать `models.py` в Task 3 и вернуться.

- [ ] **Step 7: Commit**

```bash
git add src/storage/db.py tests/storage/__init__.py tests/storage/test_db.py tests/conftest.py
git commit -m "feat(storage): add async engine, session factory, session_scope helper"
```

---

### Task 3: SQLAlchemy Base + Setting model (key/value)

**Files:**
- Create: `src/storage/models.py`
- Test: `tests/storage/test_models.py`

- [ ] **Step 1: Failing test для `Setting`**

`tests/storage/test_models.py`:

```python
"""Verify model definitions and basic persistence."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Setting


@pytest.mark.asyncio
async def test_setting_round_trip(session: AsyncSession) -> None:
    session.add(Setting(key="timezone", value="Asia/Almaty"))
    await session.commit()

    result = await session.execute(select(Setting).where(Setting.key == "timezone"))
    row = result.scalar_one()
    assert row.value == "Asia/Almaty"
```

- [ ] **Step 2: Запустить — должен упасть**

```bash
poetry run pytest tests/storage/test_models.py::test_setting_round_trip -v
```

Expected: FAIL — `ImportError: cannot import name 'Setting'` или `Base` не определён.

- [ ] **Step 3: Создать `src/storage/models.py` с `Base` и `Setting`**

```python
"""SQLAlchemy declarative models.

Models stay dumb — pure schema, no business logic. Validation and queries
live in repositories and services.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Setting(Base):
    """Global key/value store. Used for timezone, notify_preset, default_duration_min."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 4: Запустить тест — пройдёт**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/storage/models.py tests/storage/test_models.py
git commit -m "feat(storage): add Base and Setting model"
```

---

### Task 4: Client model

**Files:**
- Modify: `src/storage/models.py`
- Test: `tests/storage/test_models.py` _(добавляется тест)_

- [ ] **Step 1: Failing test для `Client`**

Дописать в `tests/storage/test_models.py`:

```python
from src.storage.models import Client


@pytest.mark.asyncio
async def test_client_unique_name_collation(session: AsyncSession) -> None:
    session.add(Client(name="Олег Иванов", instagram="oleg_insta"))
    await session.commit()

    result = await session.execute(select(Client).where(Client.name == "Олег Иванов"))
    client = result.scalar_one()
    assert client.id is not None
    assert client.instagram == "oleg_insta"
    assert client.created_at is not None


@pytest.mark.asyncio
async def test_client_optional_fields_default_none(session: AsyncSession) -> None:
    session.add(Client(name="Анна"))
    await session.commit()

    result = await session.execute(select(Client).where(Client.name == "Анна"))
    client = result.scalar_one()
    assert client.instagram is None
    assert client.notes is None
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: 2 новых FAIL — `ImportError: cannot import name 'Client'`.

- [ ] **Step 3: Добавить `Client` в `models.py`**

В `src/storage/models.py` дописать импорты и класс:

```python
from sqlalchemy import Index, Text
from sqlalchemy import DateTime as _DateTime  # noqa: F401  -- placeholder if needed
```

(Импорты — добавить недостающие; `String`, `func` уже есть.)

И класс:

```python
class Client(Base):
    """Постоянные данные клиента. Один клиент = много appointments."""

    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    instagram: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_clients_name_lower", func.lower(name)),
    )
```

- [ ] **Step 4: Запустить тесты — пройдут**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add src/storage/models.py tests/storage/test_models.py
git commit -m "feat(storage): add Client model with case-insensitive name index"
```

---

### Task 5: Appointment model with overlap-friendly index

**Files:**
- Modify: `src/storage/models.py`
- Test: `tests/storage/test_models.py` _(добавляется тест)_

- [ ] **Step 1: Failing test**

Дописать в `tests/storage/test_models.py`:

```python
from datetime import datetime, timezone

from src.storage.models import Appointment


@pytest.mark.asyncio
async def test_appointment_links_client(session: AsyncSession) -> None:
    client = Client(name="Олег")
    session.add(client)
    await session.flush()

    appt = Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
        duration_min=60,
        visit_note="маникюр",
    )
    session.add(appt)
    await session.commit()

    result = await session.execute(select(Appointment))
    saved = result.scalar_one()
    assert saved.status == "scheduled"
    assert saved.duration_min == 60
    assert saved.client_id == client.id


@pytest.mark.asyncio
async def test_appointment_cascade_delete_with_client(session: AsyncSession) -> None:
    client = Client(name="Анна")
    session.add(client)
    await session.flush()
    session.add(Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 7, 10, 0, tzinfo=timezone.utc),
    ))
    await session.commit()

    await session.delete(client)
    await session.commit()

    result = await session.execute(select(Appointment))
    assert result.scalars().all() == []
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: новые тесты FAIL — `ImportError: cannot import name 'Appointment'`.

- [ ] **Step 3: Добавить модель**

Дописать импорты в `models.py`:

```python
from sqlalchemy import ForeignKey, Integer
```

Класс:

```python
class Appointment(Base):
    """Один визит. Длительность по умолчанию 60 мин — для проверки конфликтов."""

    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    visit_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_appt_starts_status", "starts_at", "status"),
        Index("idx_appt_client", "client_id"),
    )
```

⚠️ SQLite требует `PRAGMA foreign_keys=ON` для каскада. Добавим в Task 16 при инициализации engine'а.

- [ ] **Step 4: Включить foreign keys в conftest fixture**

В `tests/conftest.py` добавить event-listener после импортов:

```python
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlite3 import Connection as SQLite3Connection


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
    if isinstance(dbapi_conn, SQLite3Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

(Aiosqlite использует `aiosqlite.Connection`, не `sqlite3.Connection` напрямую — но `dbapi_conn.driver_connection` это `sqlite3.Connection`. Если listener не сработает — заменить isinstance-проверку на `try: cursor.execute("PRAGMA foreign_keys=ON")` без проверок типа.)

Проще и надёжнее:

```python
@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
```

- [ ] **Step 5: Запустить тесты — пройдут**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: все passed.

- [ ] **Step 6: Commit**

```bash
git add src/storage/models.py tests/storage/test_models.py tests/conftest.py
git commit -m "feat(storage): add Appointment model with FK cascade and time-status index"
```

---

### Task 6: NotifyRule and ScheduledJob models

**Files:**
- Modify: `src/storage/models.py`
- Test: `tests/storage/test_models.py`

- [ ] **Step 1: Failing test**

Дописать в `test_models.py`:

```python
from src.storage.models import NotifyRule, ScheduledJob


@pytest.mark.asyncio
async def test_notify_rule_defaults(session: AsyncSession) -> None:
    rule = NotifyRule(kind="time_day_before", value="20:00")
    session.add(rule)
    await session.commit()

    result = await session.execute(select(NotifyRule))
    saved = result.scalar_one()
    assert saved.enabled is True
    assert saved.id is not None


@pytest.mark.asyncio
async def test_scheduled_job_links_appointment(session: AsyncSession) -> None:
    client = Client(name="Олег")
    session.add(client)
    await session.flush()

    appt = Appointment(
        client_id=client.id,
        starts_at=datetime(2026, 5, 6, 14, 0, tzinfo=timezone.utc),
    )
    session.add(appt)
    await session.flush()

    job = ScheduledJob(
        appointment_id=appt.id,
        fire_at=datetime(2026, 5, 5, 20, 0, tzinfo=timezone.utc),
        kind="eve_digest",
    )
    session.add(job)
    await session.commit()

    result = await session.execute(select(ScheduledJob))
    saved = result.scalar_one()
    assert saved.sent_at is None
    assert saved.kind == "eve_digest"
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: 2 новых FAIL.

- [ ] **Step 3: Добавить модели в `models.py`**

```python
from sqlalchemy import Boolean


class NotifyRule(Base):
    """Правило уведомлений (UI-настраиваемое).

    kind: time_day_before | time_same_day | offset_before
    value: для time_* — "HH:MM"; для offset_before — "60m" / "24h" / "2d"
    """

    __tablename__ = "notify_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())


class ScheduledJob(Base):
    """Запланированный пуш. Сохраняется в БД, чтобы переживать рестарты."""

    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("notify_rules.id", ondelete="SET NULL"), nullable=True
    )
    fire_at: Mapped[datetime] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("idx_jobs_fire_sent", "fire_at", "sent_at"),
    )
```

- [ ] **Step 4: Запустить — пройдут**

```bash
poetry run pytest tests/storage/test_models.py -v
```

Expected: все passed.

- [ ] **Step 5: Commit**

```bash
git add src/storage/models.py tests/storage/test_models.py
git commit -m "feat(storage): add NotifyRule and ScheduledJob models"
```

---

### Task 7: Wire models into Alembic env

**Files:**
- Modify: `src/storage/migrations/env.py:30-35` (заменить `target_metadata = None`)

- [ ] **Step 1: Заменить metadata в env.py**

В `src/storage/migrations/env.py` заменить:

```python
# Импортируется по мере добавления моделей в этапе 3:
# from src.storage.models import Base
# target_metadata = Base.metadata
target_metadata = None
```

на:

```python
from src.storage.models import Base  # noqa: E402

target_metadata = Base.metadata
```

- [ ] **Step 2: Локально (не в Docker) убедиться что alembic видит модели**

```bash
poetry run alembic check 2>&1 | head -20
```

Expected: либо "No new upgrade operations detected" (если миграции уже есть), либо ошибка про отсутствие БД — это OK, главное чтобы импорт `Base.metadata` не падал.

⚠️ Если выпадает `KeyError: 'DB_PATH'` — экспортируй временно:
```bash
DB_PATH=$(pwd)/data/bot.db poetry run alembic check
```
Папку `data/` создаст Task 8 при первой миграции.

- [ ] **Step 3: Commit**

```bash
git add src/storage/migrations/env.py
git commit -m "feat(storage): wire models metadata into alembic env"
```

---

### Task 8: Initial migration creating all 5 tables

**Files:**
- Create: `src/storage/migrations/versions/0001_initial.py`

- [ ] **Step 1: Сгенерировать миграцию автогенерацией**

```bash
mkdir -p data
DB_PATH=$(pwd)/data/bot.db poetry run alembic revision --autogenerate -m "initial schema"
```

Expected: создан файл `src/storage/migrations/versions/<random>_initial_schema.py`.

- [ ] **Step 2: Переименовать в стабильное имя `0001_initial.py`**

```bash
mv src/storage/migrations/versions/*_initial_schema.py src/storage/migrations/versions/0001_initial.py
```

- [ ] **Step 3: Открыть файл и проверить — должны быть `op.create_table` для clients, appointments, notify_rules, scheduled_jobs, settings**

Прочесть `src/storage/migrations/versions/0001_initial.py`. Убедиться:
- 5 `op.create_table` (clients, appointments, notify_rules, scheduled_jobs, settings)
- foreign keys на appointments.client_id, scheduled_jobs.appointment_id, scheduled_jobs.rule_id
- индексы на clients (case-insensitive по имени), appointments (starts_at, status), scheduled_jobs (fire_at, sent_at)

⚠️ Если автогенерация не подхватила case-insensitive index — добавить вручную в `upgrade()`:

```python
op.create_index(
    "idx_clients_name_lower",
    "clients",
    [sa.text("lower(name)")],
    unique=False,
)
```

И симметрично в `downgrade()`:
```python
op.drop_index("idx_clients_name_lower", table_name="clients")
```

- [ ] **Step 4: Применить миграцию локально**

```bash
DB_PATH=$(pwd)/data/bot.db poetry run alembic upgrade head
```

Expected: `INFO [alembic.runtime.migration] Running upgrade  -> 0001, initial schema`.

- [ ] **Step 5: Проверить таблицы**

```bash
poetry run python -c "import sqlite3; c = sqlite3.connect('data/bot.db'); print([r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()])"
```

Expected output: список включает `alembic_version`, `clients`, `appointments`, `notify_rules`, `scheduled_jobs`, `settings`.

- [ ] **Step 6: Удалить локальную БД (она в `.gitignore`, но на всякий случай)**

```bash
rm -f data/bot.db
```

- [ ] **Step 7: Commit миграции**

```bash
git add src/storage/migrations/versions/0001_initial.py
git status -s
```

Убедиться что `data/bot.db` НЕ в staging.

```bash
git commit -m "feat(storage): initial migration creating all five tables"
```

---

### Task 9: ClientRepository with CRUD and search

**Files:**
- Create: `src/storage/repositories/__init__.py`, `src/storage/repositories/clients.py`
- Test: `tests/storage/test_repositories.py`

- [ ] **Step 1: Создать пустой `repositories/__init__.py`**

```python
"""Repository layer — typed accessors for models."""

from src.storage.repositories.clients import ClientRepository

__all__ = ["ClientRepository"]
```

- [ ] **Step 2: Failing test**

Создать `tests/storage/test_repositories.py`:

```python
"""Repository-layer tests (using in-memory SQLite from conftest)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.clients import ClientRepository


@pytest.mark.asyncio
async def test_create_and_get_by_id(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Олег", instagram="oleg_insta", notes="любит чай")

    fetched = await repo.get(client.id)
    assert fetched is not None
    assert fetched.name == "Олег"
    assert fetched.instagram == "oleg_insta"


@pytest.mark.asyncio
async def test_search_by_name_case_insensitive(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    await repo.create(name="Анна Петрова")
    await repo.create(name="Олег Иванов")
    await repo.create(name="анна сидорова")

    results = await repo.search_by_name("анн")
    names = [c.name for c in results]
    assert "Анна Петрова" in names
    assert "анна сидорова" in names
    assert "Олег Иванов" not in names


@pytest.mark.asyncio
async def test_list_recent(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    for n in ["a", "b", "c", "d", "e"]:
        await repo.create(name=n)

    recent = await repo.list_recent(limit=3)
    assert len(recent) == 3


@pytest.mark.asyncio
async def test_update_partial(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Олег")
    updated = await repo.update(client.id, instagram="oleg2", notes="VIP")

    assert updated is not None
    assert updated.instagram == "oleg2"
    assert updated.notes == "VIP"
    assert updated.name == "Олег"  # не изменилось


@pytest.mark.asyncio
async def test_delete(session: AsyncSession) -> None:
    repo = ClientRepository(session)
    client = await repo.create(name="Tmp")
    deleted = await repo.delete(client.id)
    assert deleted is True

    fetched = await repo.get(client.id)
    assert fetched is None
```

- [ ] **Step 3: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: 5 FAIL — `ImportError`.

- [ ] **Step 4: Реализовать `ClientRepository`**

`src/storage/repositories/clients.py`:

```python
"""Client repository — CRUD and case-insensitive name search."""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Client


class ClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        instagram: str | None = None,
        notes: str | None = None,
    ) -> Client:
        client = Client(name=name, instagram=instagram, notes=notes)
        self._session.add(client)
        await self._session.flush()
        return client

    async def get(self, client_id: int) -> Client | None:
        return await self._session.get(Client, client_id)

    async def search_by_name(self, query: str, *, limit: int = 20) -> list[Client]:
        pattern = f"%{query.lower()}%"
        stmt = (
            select(Client)
            .where(func.lower(Client.name).like(pattern))
            .order_by(Client.name)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def list_recent(self, *, limit: int = 10) -> list[Client]:
        stmt = select(Client).order_by(desc(Client.created_at)).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def update(
        self,
        client_id: int,
        *,
        name: str | None = None,
        instagram: str | None = None,
        notes: str | None = None,
    ) -> Client | None:
        client = await self.get(client_id)
        if client is None:
            return None
        if name is not None:
            client.name = name
        if instagram is not None:
            client.instagram = instagram
        if notes is not None:
            client.notes = notes
        await self._session.flush()
        return client

    async def delete(self, client_id: int) -> bool:
        client = await self.get(client_id)
        if client is None:
            return False
        await self._session.delete(client)
        await self._session.flush()
        return True
```

- [ ] **Step 5: Запустить — пройдут**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/storage/repositories/__init__.py src/storage/repositories/clients.py tests/storage/test_repositories.py
git commit -m "feat(storage): add ClientRepository with CRUD and case-insensitive search"
```

---

### Task 10: AppointmentRepository with overlap query

**Files:**
- Create: `src/storage/repositories/appointments.py`
- Modify: `src/storage/repositories/__init__.py`
- Test: `tests/storage/test_repositories.py` _(добавляются тесты)_

- [ ] **Step 1: Failing test для overlap-логики**

Дописать в `tests/storage/test_repositories.py`:

```python
from datetime import datetime, timedelta, timezone

from src.storage.repositories.appointments import AppointmentRepository


def _utc(year: int, month: int, day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(year, month, day, hh, mm, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_create_appointment_for_client(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="Олег")

    appt = await appts.create(
        client_id=client.id,
        starts_at=_utc(2026, 5, 6, 14),
        duration_min=60,
        visit_note="маникюр",
    )
    assert appt.id is not None
    assert appt.status == "scheduled"


@pytest.mark.asyncio
async def test_find_overlap_includes_partial(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, 14), duration_min=60
    )

    # Новый слот 14:30-15:30 пересекается с 14:00-15:00
    conflict = await appts.find_overlap(
        starts_at=_utc(2026, 5, 6, 14, 30), duration_min=60
    )
    assert len(conflict) == 1


@pytest.mark.asyncio
async def test_find_overlap_excludes_back_to_back(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, 14), duration_min=60
    )

    # 15:00-16:00 — впритык, не пересекается
    conflict = await appts.find_overlap(
        starts_at=_utc(2026, 5, 6, 15), duration_min=60
    )
    assert conflict == []


@pytest.mark.asyncio
async def test_find_overlap_excludes_cancelled(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    a = await appts.create(
        client_id=client.id, starts_at=_utc(2026, 5, 6, 14), duration_min=60
    )
    await appts.update_status(a.id, "cancelled")

    conflict = await appts.find_overlap(
        starts_at=_utc(2026, 5, 6, 14, 30), duration_min=60
    )
    assert conflict == []


@pytest.mark.asyncio
async def test_list_in_range(session: AsyncSession) -> None:
    clients = ClientRepository(session)
    appts = AppointmentRepository(session)
    client = await clients.create(name="A")
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 9))
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 6, 18))
    await appts.create(client_id=client.id, starts_at=_utc(2026, 5, 7, 10))

    result = await appts.list_in_range(
        start=_utc(2026, 5, 6, 0), end=_utc(2026, 5, 7, 0)
    )
    assert len(result) == 2
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: новые FAIL.

- [ ] **Step 3: Реализовать `AppointmentRepository`**

`src/storage/repositories/appointments.py`:

```python
"""Appointment repository — CRUD, overlap detection, range queries."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Appointment


class AppointmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        client_id: int,
        starts_at: datetime,
        duration_min: int = 60,
        visit_note: str | None = None,
    ) -> Appointment:
        appt = Appointment(
            client_id=client_id,
            starts_at=starts_at,
            duration_min=duration_min,
            visit_note=visit_note,
        )
        self._session.add(appt)
        await self._session.flush()
        return appt

    async def get(self, appointment_id: int) -> Appointment | None:
        return await self._session.get(Appointment, appointment_id)

    async def update_status(self, appointment_id: int, status: str) -> Appointment | None:
        appt = await self.get(appointment_id)
        if appt is None:
            return None
        appt.status = status
        await self._session.flush()
        return appt

    async def reschedule(
        self,
        appointment_id: int,
        *,
        starts_at: datetime,
        duration_min: int | None = None,
    ) -> Appointment | None:
        appt = await self.get(appointment_id)
        if appt is None:
            return None
        appt.starts_at = starts_at
        if duration_min is not None:
            appt.duration_min = duration_min
        await self._session.flush()
        return appt

    async def find_overlap(
        self,
        *,
        starts_at: datetime,
        duration_min: int,
        exclude_id: int | None = None,
    ) -> list[Appointment]:
        """Return scheduled appointments overlapping the proposed slot.

        Two intervals [a,b) and [c,d) overlap iff a < d and c < b.
        """
        ends_at = starts_at + timedelta(minutes=duration_min)
        # b > c  AND  a < d  →  Appointment.ends > new_start AND Appointment.start < new_end
        # Where Appointment.ends = starts_at + duration_min minutes
        # SQLite не имеет интервальной арифметики из коробки → считаем в Python:
        # выбираем кандидатов в широком окне ±24h, фильтруем в Python.
        candidates_stmt = (
            select(Appointment)
            .where(
                Appointment.status == "scheduled",
                Appointment.starts_at >= starts_at - timedelta(hours=24),
                Appointment.starts_at <= ends_at + timedelta(hours=24),
            )
        )
        if exclude_id is not None:
            candidates_stmt = candidates_stmt.where(Appointment.id != exclude_id)

        result = await self._session.execute(candidates_stmt)
        candidates = list(result.scalars())

        overlapping: list[Appointment] = []
        for a in candidates:
            a_end = a.starts_at + timedelta(minutes=a.duration_min)
            if a.starts_at < ends_at and starts_at < a_end:
                overlapping.append(a)
        return overlapping

    async def list_in_range(
        self, *, start: datetime, end: datetime, statuses: tuple[str, ...] = ("scheduled",)
    ) -> list[Appointment]:
        stmt = (
            select(Appointment)
            .where(
                and_(
                    Appointment.starts_at >= start,
                    Appointment.starts_at < end,
                    Appointment.status.in_(statuses),
                )
            )
            .order_by(Appointment.starts_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars())

    async def delete(self, appointment_id: int) -> bool:
        appt = await self.get(appointment_id)
        if appt is None:
            return False
        await self._session.delete(appt)
        await self._session.flush()
        return True
```

- [ ] **Step 4: Обновить `repositories/__init__.py`**

```python
"""Repository layer — typed accessors for models."""

from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

__all__ = ["AppointmentRepository", "ClientRepository"]
```

- [ ] **Step 5: Запустить — пройдут**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: все passed (5 client + 5 appointment = 10).

- [ ] **Step 6: Commit**

```bash
git add src/storage/repositories/appointments.py src/storage/repositories/__init__.py tests/storage/test_repositories.py
git commit -m "feat(storage): add AppointmentRepository with overlap detection"
```

---

### Task 11: NotifyRuleRepository

**Files:**
- Create: `src/storage/repositories/notify_rules.py`
- Modify: `src/storage/repositories/__init__.py`
- Test: `tests/storage/test_repositories.py`

- [ ] **Step 1: Failing test**

Дописать:

```python
from src.storage.repositories.notify_rules import NotifyRuleRepository


@pytest.mark.asyncio
async def test_notify_rule_create_and_list_enabled(session: AsyncSession) -> None:
    repo = NotifyRuleRepository(session)
    await repo.create(kind="time_day_before", value="20:00", enabled=True)
    await repo.create(kind="time_same_day", value="09:00", enabled=True)
    await repo.create(kind="offset_before", value="60m", enabled=False)

    enabled = await repo.list_enabled()
    assert len(enabled) == 2
    kinds = {r.kind for r in enabled}
    assert kinds == {"time_day_before", "time_same_day"}


@pytest.mark.asyncio
async def test_notify_rule_toggle(session: AsyncSession) -> None:
    repo = NotifyRuleRepository(session)
    rule = await repo.create(kind="offset_before", value="60m", enabled=False)

    toggled = await repo.set_enabled(rule.id, True)
    assert toggled is not None
    assert toggled.enabled is True


@pytest.mark.asyncio
async def test_notify_rule_replace_all(session: AsyncSession) -> None:
    repo = NotifyRuleRepository(session)
    await repo.create(kind="offset_before", value="60m")
    await repo.create(kind="offset_before", value="24h")

    await repo.replace_all([
        ("time_day_before", "20:00", True),
        ("time_same_day", "09:00", True),
    ])

    all_rules = await repo.list_all()
    assert len(all_rules) == 2
    assert {r.kind for r in all_rules} == {"time_day_before", "time_same_day"}
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: 3 FAIL.

- [ ] **Step 3: Реализовать**

`src/storage/repositories/notify_rules.py`:

```python
"""Notify-rule repository — CRUD plus a bulk replace for preset switching."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import NotifyRule


class NotifyRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, kind: str, value: str, enabled: bool = True
    ) -> NotifyRule:
        rule = NotifyRule(kind=kind, value=value, enabled=enabled)
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def get(self, rule_id: int) -> NotifyRule | None:
        return await self._session.get(NotifyRule, rule_id)

    async def list_all(self) -> list[NotifyRule]:
        result = await self._session.execute(select(NotifyRule).order_by(NotifyRule.id))
        return list(result.scalars())

    async def list_enabled(self) -> list[NotifyRule]:
        result = await self._session.execute(
            select(NotifyRule).where(NotifyRule.enabled.is_(True)).order_by(NotifyRule.id)
        )
        return list(result.scalars())

    async def set_enabled(self, rule_id: int, enabled: bool) -> NotifyRule | None:
        rule = await self.get(rule_id)
        if rule is None:
            return None
        rule.enabled = enabled
        await self._session.flush()
        return rule

    async def update_value(self, rule_id: int, value: str) -> NotifyRule | None:
        rule = await self.get(rule_id)
        if rule is None:
            return None
        rule.value = value
        await self._session.flush()
        return rule

    async def delete(self, rule_id: int) -> bool:
        rule = await self.get(rule_id)
        if rule is None:
            return False
        await self._session.delete(rule)
        await self._session.flush()
        return True

    async def replace_all(self, rules: list[tuple[str, str, bool]]) -> None:
        """Wipe table and insert new tuples (kind, value, enabled)."""
        await self._session.execute(delete(NotifyRule))
        for kind, value, enabled in rules:
            self._session.add(NotifyRule(kind=kind, value=value, enabled=enabled))
        await self._session.flush()
```

- [ ] **Step 4: Обновить `repositories/__init__.py`**

```python
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository

__all__ = ["AppointmentRepository", "ClientRepository", "NotifyRuleRepository"]
```

- [ ] **Step 5: Запустить — пройдут**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: passed.

- [ ] **Step 6: Commit**

```bash
git add src/storage/repositories/notify_rules.py src/storage/repositories/__init__.py tests/storage/test_repositories.py
git commit -m "feat(storage): add NotifyRuleRepository with bulk replace"
```

---

### Task 12: SettingRepository (typed key/value)

**Files:**
- Create: `src/storage/repositories/settings.py`
- Modify: `src/storage/repositories/__init__.py`
- Test: `tests/storage/test_repositories.py`

- [ ] **Step 1: Failing test**

```python
from src.storage.repositories.settings import SettingRepository


@pytest.mark.asyncio
async def test_setting_get_returns_none_when_missing(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    assert await repo.get("missing") is None


@pytest.mark.asyncio
async def test_setting_set_then_get(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    await repo.set("timezone", "Asia/Almaty")

    val = await repo.get("timezone")
    assert val == "Asia/Almaty"


@pytest.mark.asyncio
async def test_setting_set_overwrites(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    await repo.set("preset", "eve_morning")
    await repo.set("preset", "eve_only")

    assert await repo.get("preset") == "eve_only"


@pytest.mark.asyncio
async def test_setting_get_int(session: AsyncSession) -> None:
    repo = SettingRepository(session)
    await repo.set("default_duration_min", "60")
    assert await repo.get_int("default_duration_min") == 60
    assert await repo.get_int("missing", default=15) == 15
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: FAIL.

- [ ] **Step 3: Реализовать**

`src/storage/repositories/settings.py`:

```python
"""Settings repository — typed convenience wrappers around key/value storage."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Setting


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> str | None:
        row = await self._session.get(Setting, key)
        return row.value if row is not None else None

    async def get_int(self, key: str, *, default: int | None = None) -> int | None:
        raw = await self.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    async def set(self, key: str, value: str) -> None:
        existing = await self._session.get(Setting, key)
        if existing is None:
            self._session.add(Setting(key=key, value=value))
        else:
            existing.value = value
        await self._session.flush()
```

- [ ] **Step 4: Обновить `__init__.py`**

```python
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository
from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.settings import SettingRepository

__all__ = [
    "AppointmentRepository",
    "ClientRepository",
    "NotifyRuleRepository",
    "SettingRepository",
]
```

- [ ] **Step 5: Запустить — пройдут**

```bash
poetry run pytest tests/storage/test_repositories.py -v
```

Expected: passed.

- [ ] **Step 6: Commit**

```bash
git add src/storage/repositories/settings.py src/storage/repositories/__init__.py tests/storage/test_repositories.py
git commit -m "feat(storage): add SettingRepository with typed get/set"
```

---

### Task 13: settings_service with default seed

**Files:**
- Create: `src/services/settings_service.py`
- Test: `tests/services/__init__.py`, `tests/services/test_settings_service.py`

- [ ] **Step 1: Создать пустой `tests/services/__init__.py`**

```python
```

- [ ] **Step 2: Failing test**

`tests/services/test_settings_service.py`:

```python
"""Tests for settings_service: seed defaults and helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services import settings_service
from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.settings import SettingRepository


@pytest.mark.asyncio
async def test_seed_creates_defaults_if_empty(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)

    settings_repo = SettingRepository(session)
    rules_repo = NotifyRuleRepository(session)

    assert await settings_repo.get("timezone") == "Asia/Almaty"
    assert await settings_repo.get("notify_preset") == "eve_morning"
    assert await settings_repo.get_int("default_duration_min") == 60

    rules = await rules_repo.list_enabled()
    assert {(r.kind, r.value) for r in rules} == {
        ("time_day_before", "20:00"),
        ("time_same_day", "09:00"),
    }


@pytest.mark.asyncio
async def test_seed_is_idempotent(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)
    await settings_service.seed_defaults(session)

    rules = await NotifyRuleRepository(session).list_all()
    assert len(rules) == 2  # не удвоилось


@pytest.mark.asyncio
async def test_get_timezone(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)
    tz = await settings_service.get_timezone(session)
    assert str(tz) == "Asia/Almaty"


@pytest.mark.asyncio
async def test_get_default_duration(session: AsyncSession) -> None:
    await settings_service.seed_defaults(session)
    assert await settings_service.get_default_duration_min(session) == 60
```

- [ ] **Step 3: Запустить — упадёт**

```bash
poetry run pytest tests/services/test_settings_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.services.settings_service'`.

- [ ] **Step 4: Реализовать**

`src/services/settings_service.py`:

```python
"""High-level settings access plus default seeding.

`seed_defaults` is idempotent and intended to be called once on startup.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.repositories.notify_rules import NotifyRuleRepository
from src.storage.repositories.settings import SettingRepository

DEFAULT_TIMEZONE = "Asia/Almaty"
DEFAULT_PRESET = "eve_morning"
DEFAULT_DURATION_MIN = 60
DEFAULT_RULES: list[tuple[str, str, bool]] = [
    ("time_day_before", "20:00", True),
    ("time_same_day", "09:00", True),
]


async def seed_defaults(session: AsyncSession) -> None:
    """Insert default settings and notify_rules if missing. Idempotent."""
    settings_repo = SettingRepository(session)
    rules_repo = NotifyRuleRepository(session)

    if await settings_repo.get("timezone") is None:
        await settings_repo.set("timezone", DEFAULT_TIMEZONE)
    if await settings_repo.get("notify_preset") is None:
        await settings_repo.set("notify_preset", DEFAULT_PRESET)
    if await settings_repo.get("default_duration_min") is None:
        await settings_repo.set("default_duration_min", str(DEFAULT_DURATION_MIN))

    existing_rules = await rules_repo.list_all()
    if not existing_rules:
        for kind, value, enabled in DEFAULT_RULES:
            await rules_repo.create(kind=kind, value=value, enabled=enabled)


async def get_timezone(session: AsyncSession) -> ZoneInfo:
    raw = await SettingRepository(session).get("timezone") or DEFAULT_TIMEZONE
    return ZoneInfo(raw)


async def get_default_duration_min(session: AsyncSession) -> int:
    repo = SettingRepository(session)
    val = await repo.get_int("default_duration_min", default=DEFAULT_DURATION_MIN)
    assert val is not None
    return val


async def get_preset(session: AsyncSession) -> str:
    return await SettingRepository(session).get("notify_preset") or DEFAULT_PRESET


async def set_preset(session: AsyncSession, preset: str) -> None:
    await SettingRepository(session).set("notify_preset", preset)


async def set_timezone(session: AsyncSession, tz: str) -> None:
    ZoneInfo(tz)  # raises ZoneInfoNotFoundError if invalid
    await SettingRepository(session).set("timezone", tz)


async def set_default_duration_min(session: AsyncSession, minutes: int) -> None:
    if minutes <= 0:
        raise ValueError("duration must be positive")
    await SettingRepository(session).set("default_duration_min", str(minutes))
```

- [ ] **Step 5: Запустить — пройдут**

```bash
poetry run pytest tests/services/test_settings_service.py -v
```

Expected: passed.

- [ ] **Step 6: Commit**

```bash
git add src/services/settings_service.py tests/services/__init__.py tests/services/test_settings_service.py
git commit -m "feat(services): add settings_service with idempotent default seed"
```

---

### Task 14: WhitelistMiddleware

**Files:**
- Create: `src/bot/middlewares/whitelist.py`
- Test: `tests/bot/__init__.py`, `tests/bot/test_whitelist_middleware.py`

- [ ] **Step 1: Создать пустой `tests/bot/__init__.py`**

```python
```

- [ ] **Step 2: Failing test**

`tests/bot/test_whitelist_middleware.py`:

```python
"""WhitelistMiddleware tests — owner gets through, everyone else is silently dropped."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, Update, User

from src.bot.middlewares.whitelist import WhitelistMiddleware


def _make_message(user_id: int) -> Update:
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    msg = Message(
        message_id=1,
        date=1700000000,  # type: ignore[arg-type]
        chat=chat,
        from_user=user,
        text="/start",
    )
    return Update(update_id=1, message=msg)


@pytest.mark.asyncio
async def test_owner_passes_through() -> None:
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(owner_chat_id=42)
    update = _make_message(user_id=42)

    result = await mw(handler, update, {})

    handler.assert_awaited_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_non_owner_is_silently_dropped() -> None:
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(owner_chat_id=42)
    update = _make_message(user_id=999)

    result = await mw(handler, update, {})

    handler.assert_not_awaited()
    assert result is None


@pytest.mark.asyncio
async def test_update_without_user_is_dropped() -> None:
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(owner_chat_id=42)
    update = Update(update_id=1)  # no message

    result = await mw(handler, update, {})

    handler.assert_not_awaited()
    assert result is None
```

- [ ] **Step 3: Запустить — упадёт**

```bash
poetry run pytest tests/bot/test_whitelist_middleware.py -v
```

Expected: FAIL — модуль отсутствует.

- [ ] **Step 4: Реализовать**

`src/bot/middlewares/whitelist.py`:

```python
"""Whitelist middleware — drops every update not from OWNER_CHAT_ID.

Silent drop (no reply) — это намеренно: бот не должен подтверждать своё
существование чужим пользователям.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

log = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    def __init__(self, *, owner_chat_id: int) -> None:
        super().__init__()
        self._owner_chat_id = owner_chat_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)
        if user_id is None:
            log.debug("dropping update without user: %r", type(event).__name__)
            return None
        if user_id != self._owner_chat_id:
            log.warning("unauthorized access attempt: user_id=%s", user_id)
            return None
        return await handler(event, data)

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> int | None:
        # Update wraps message/callback_query/etc. — нам нужен from_user.id из любого.
        if isinstance(event, Update):
            for candidate in (
                event.message,
                event.edited_message,
                event.callback_query,
                event.inline_query,
                event.chosen_inline_result,
                event.my_chat_member,
                event.chat_member,
                event.shipping_query,
                event.pre_checkout_query,
                event.poll_answer,
            ):
                if candidate is not None and getattr(candidate, "from_user", None) is not None:
                    return candidate.from_user.id  # type: ignore[union-attr]
            return None
        # Если middleware подключён на уровне message-router'а — event это уже Message
        from_user = getattr(event, "from_user", None)
        return from_user.id if from_user is not None else None
```

- [ ] **Step 5: Запустить — пройдут**

```bash
poetry run pytest tests/bot/test_whitelist_middleware.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/bot/middlewares/whitelist.py tests/bot/__init__.py tests/bot/test_whitelist_middleware.py
git commit -m "feat(bot): add WhitelistMiddleware with silent drop for non-owners"
```

---

### Task 15: Main menu keyboard

**Files:**
- Create: `src/bot/keyboards/main_menu.py`
- Test: `tests/bot/test_keyboards.py`

- [ ] **Step 1: Failing test**

`tests/bot/test_keyboards.py`:

```python
"""Keyboard layout tests."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup

from src.bot.keyboards.main_menu import main_menu_kb


def test_main_menu_has_required_buttons() -> None:
    kb = main_menu_kb()
    assert isinstance(kb, ReplyKeyboardMarkup)

    labels = {btn.text for row in kb.keyboard for btn in row}
    assert "+ Запись" in labels
    assert "📅 Сегодня" in labels
    assert "📆 Завтра" in labels
    assert "👥 Клиенты" in labels
    assert "⚙️ Настройки" in labels
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/bot/test_keyboards.py -v
```

Expected: FAIL — модуль отсутствует.

- [ ] **Step 3: Реализовать**

`src/bot/keyboards/main_menu.py`:

```python
"""Main menu — reply-keyboard, всегда доступная owner'у."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="+ Запись")],
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="📆 Завтра")],
            [KeyboardButton(text="🗓 Неделя"), KeyboardButton(text="👥 Клиенты")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
```

- [ ] **Step 4: Запустить — пройдёт**

```bash
poetry run pytest tests/bot/test_keyboards.py -v
```

Expected: passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/keyboards/main_menu.py tests/bot/test_keyboards.py
git commit -m "feat(bot): add main menu reply keyboard"
```

---

### Task 16: /start handler

**Files:**
- Create: `src/bot/handlers/start.py`
- Test: `tests/bot/test_start_handler.py`

- [ ] **Step 1: Failing test**

`tests/bot/test_start_handler.py`:

```python
"""/start handler test — sends welcome with main menu keyboard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers.start import handle_start


@pytest.mark.asyncio
async def test_start_replies_with_menu() -> None:
    message = MagicMock()
    message.answer = AsyncMock()
    message.from_user = MagicMock(first_name="Юля")

    await handle_start(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Юля" in text or "Привет" in text
    assert kwargs.get("reply_markup") is not None
```

- [ ] **Step 2: Запустить — упадёт**

```bash
poetry run pytest tests/bot/test_start_handler.py -v
```

Expected: FAIL.

- [ ] **Step 3: Реализовать**

`src/bot/handlers/start.py`:

```python
"""/start command handler — greets the owner and shows the main menu."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.keyboards.main_menu import main_menu_kb

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "владелец"
    await message.answer(
        text=(
            f"Привет, {name}!\n"
            f"Я твой ассистент для записей.\n"
            f"Жми «+ Запись» чтобы начать, или /help для списка команд."
        ),
        reply_markup=main_menu_kb(),
    )
```

- [ ] **Step 4: Запустить — пройдёт**

```bash
poetry run pytest tests/bot/test_start_handler.py -v
```

Expected: passed.

- [ ] **Step 5: Commit**

```bash
git add src/bot/handlers/start.py tests/bot/test_start_handler.py
git commit -m "feat(bot): add /start handler with main menu greeting"
```

---

### Task 17: Wire everything in main.py

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Заменить функцию `_build_dispatcher` и добавить startup**

Открыть `src/main.py`. Заменить блок целиком:

```python
"""Bot bootstrap.

Startup pipeline:
1. Load config (validates env)
2. Configure logging
3. Build async DB engine
4. Run pending Alembic migrations programmatically (skipped here — handled by docker-compose entrypoint)
5. Seed defaults (idempotent)
6. Build dispatcher: Redis FSM storage + WhitelistMiddleware + routers
7. Start polling
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import timedelta

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from src.bot.handlers import start as start_handlers
from src.bot.middlewares.whitelist import WhitelistMiddleware
from src.config import Settings, ensure_data_dir, load_settings
from src.services import settings_service
from src.storage import db


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.INFO)


async def _seed_defaults(settings: Settings) -> None:
    engine = db.create_engine(settings.db_url)
    factory = db.create_session_factory(engine)
    try:
        async with db.session_scope(factory) as session:
            await settings_service.seed_defaults(session)
    finally:
        await engine.dispose()


def _build_dispatcher(settings: Settings) -> Dispatcher:
    storage = RedisStorage.from_url(
        settings.redis_url,
        state_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
        data_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
    )
    dp = Dispatcher(storage=storage)

    # Whitelist must be registered BEFORE routers so it intercepts all updates.
    dp.update.outer_middleware(WhitelistMiddleware(owner_chat_id=settings.owner_chat_id))

    dp.include_router(start_handlers.router)
    return dp


async def run() -> None:
    settings = load_settings()
    _configure_logging(settings.log_level)
    ensure_data_dir(settings)

    log = logging.getLogger("bot")
    log.info(
        "Starting bot, owner=%s tz=%s stt=%s",
        settings.owner_chat_id, settings.owner_tz, settings.stt_provider,
    )

    await _seed_defaults(settings)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = _build_dispatcher(settings)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Запустить весь набор тестов**

```bash
poetry run pytest -v
```

Expected: все passed (~25 тестов: storage models + repos + service + middleware + keyboard + start + smoke config).

- [ ] **Step 3: Запустить ruff и mypy**

```bash
poetry run ruff check src tests
poetry run mypy src
```

Expected: no errors. Если есть — исправить inline (импорты, типы).

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat: wire whitelist middleware and start router into main.py"
```

---

### Task 18: End-to-end smoke (manual)

**Files:** none (only verification)

- [ ] **Step 1: Подготовить локальный `.env`**

```bash
cp .env.example .env
```

Открыть `.env` и заполнить:
- `BOT_TOKEN` — реальный токен от @BotFather (для тестового бота)
- `OWNER_CHAT_ID` — твой Telegram user id (узнать через @userinfobot)
- `OPENAI_API_KEY` — любая непустая строка `"sk-test"` (этот этап ещё не использует OpenAI, но валидатор требует)

- [ ] **Step 2: Запустить через docker-compose**

```bash
docker compose up --build
```

Expected: оба контейнера стартуют (bot и redis), в логах bot — `Starting bot, owner=… tz=Asia/Almaty stt=openai`, затем `INFO aiogram.dispatcher: Run polling for bot @<your_bot>`.

- [ ] **Step 3: В Telegram написать боту `/start`**

Expected:
- Бот отвечает: "Привет, <имя>! Я твой ассистент для записей. Жми «+ Запись» чтобы начать, или /help для списка команд."
- Появляется reply-keyboard с 5 кнопками: `+ Запись`, `📅 Сегодня`, `📆 Завтра`, `🗓 Неделя`, `👥 Клиенты`, `⚙️ Настройки`.

- [ ] **Step 4: Проверить whitelist**

С чужого аккаунта (или попросить кого-то) написать `/start` — бот **молчит**.
В логах bot — запись `WARNING ... unauthorized access attempt: user_id=<other_id>`.

- [ ] **Step 5: Проверить БД**

```bash
docker compose exec bot sqlite3 /data/bot.db ".tables"
```

Expected: `alembic_version  appointments  clients  notify_rules  scheduled_jobs  settings`.

```bash
docker compose exec bot sqlite3 /data/bot.db "SELECT * FROM settings;"
```

Expected:
```
default_duration_min|60|<timestamp>
notify_preset|eve_morning|<timestamp>
timezone|Asia/Almaty|<timestamp>
```

```bash
docker compose exec bot sqlite3 /data/bot.db "SELECT kind, value, enabled FROM notify_rules;"
```

Expected:
```
time_day_before|20:00|1
time_same_day|09:00|1
```

- [ ] **Step 6: Остановить compose, проверить .gitignore работает**

```bash
docker compose down
git status -s
```

Expected: НЕТ `data/`, `*.db`, `redis-data/`, `.env` в untracked.

- [ ] **Step 7: Финальный commit плана**

```bash
git status
git log --oneline plan/foundation
```

Expected: ~17-18 коммитов на ветке `plan/foundation`.

- [ ] **Step 8: Merge в main**

```bash
git checkout -b main 2>/dev/null || git checkout main
git merge --no-ff plan/foundation -m "feat: foundation — storage, whitelist, /start"
```

(Если main ещё не существует — на этапе init был `master` или текущая default-ветка. Подстроиться.)

---

## Plan complete

После Task 18 у тебя:
- ✅ Бот стартует через `docker compose up`
- ✅ Отвечает `/start` главным меню
- ✅ Whitelist режет чужих
- ✅ БД создана с пятью таблицами + дефолтные настройки
- ✅ Все unit-тесты зелёные (~25 штук)
- ✅ ruff + mypy clean

Следующий план — **2026-05-XX-booking-core.md** — добавит FSM-форму создания записи, гибридный date picker, проверку конфликтов, `/today/tomorrow/week`, карточку записи. Перед его запуском убедись что Foundation работает на боевом VM.
