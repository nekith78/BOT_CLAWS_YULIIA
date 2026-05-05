# Claude rules for BOT_CLAWS_YULIIA

This file is read by Claude Code at the start of every session in this repo.
It defines project-specific rules. Global rules (`~/.claude/CLAUDE.md`) and
user instructions take precedence over this file.

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
  alembic). Repository-pattern над моделями. Бот — single-user, whitelist
  по `OWNER_CHAT_ID` через `WhitelistMiddleware`.
- **Полная спецификация** — на машине пользователя в
  `~/.claude/plans/swirling-whistling-tulip.md`. Подробные планы реализации
  лежат в `docs/superpowers/plans/` (Foundation готов; впереди Booking core,
  Notifications, Voice intake, Deploy и др.).
