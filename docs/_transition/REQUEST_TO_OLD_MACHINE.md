# Запрос на сбор переходного пакета (Windows → Mac)

> **Как использовать:** скопируй весь текст ниже (от `# Контекст` до конца файла)
> и вставь в новой сессии Claude Code, открытой в проекте `BOT_CLAWS_YULIIA`
> на Windows-машине.

---

# Контекст

Репозиторий `BOT_CLAWS_YULIIA` уже перенесён на Mac через `git push` → `git clone`.
Всё, что было **в git**, доехало корректно. Но многие важные файлы лежали
**вне git** (в `~/.claude/`, в `.gitignore`-папках, в твоей памяти-сессии и т.д.)
и до Mac не дошли. Нужно собрать их в один пакет, положить в репо и запушить —
на Mac я сделаю `git pull`.

# Что собрать

## 1. Полная спецификация проекта (главное)

Найти и прочитать целиком:

```bash
ls "$HOME/.claude/plans/" | grep -i -E "(swirling|whistling|tulip|bot|claws|yuliia|appointment|booking)"
# Главная цель: ~/.claude/plans/swirling-whistling-tulip.md
```

Также проверить:
- Все `.md` в `~/.claude/plans/`, в названии или содержимом которых
  упоминается `BOT_CLAWS_YULIIA`, "бот", "Юлия", "маникюр", "appointment",
  "booking", "voice intake", "notify".
- На всякий случай поиск во всём `~/.claude/`:
  ```bash
  grep -rl -i "BOT_CLAWS_YULIIA\|swirling-whistling-tulip" "$HOME/.claude/" 2>/dev/null
  ```

## 2. Project memory

Содержимое всех файлов из:

```bash
ls "$HOME/.claude/projects/" | grep -i "BOT-CLAWS-YULIIA"
# Скопировать содержимое: ~/.claude/projects/<slug>/memory/*.md
```

## 3. Любые незакоммиченные черновики в самом репо

```bash
cd <путь к BOT_CLAWS_YULIIA на Windows>   # обычно e:\BOT_CLAWS_YULIIA
git status --ignored                       # покажет также gitignored файлы
ls -la .claude/ 2>/dev/null                # локальные настройки/хуки в репо
ls -la docs/superpowers/                   # specs/ может быть рядом с plans/
```

Собрать всё, что есть в `docs/`, чего ещё нет в master (особенно подкаталог
`docs/superpowers/specs/` — он упомянут в README, но на Mac его нет).

## 4. Кастомные настройки и хуки Claude Code

- `.claude/settings.json` или `.claude/settings.local.json` в **корне репо**
  (если они есть и не закоммичены).
- Релевантные разделы из `~/.claude/settings.json` (хуки, permissions,
  переменные окружения, относящиеся к этому проекту).
- `.git/hooks/post-commit` — текст хука graphify, чтобы я мог его
  воспроизвести без переустановки `graphifyy`.

## 5. Сгенерированный граф (опционально, но полезно)

```bash
ls graphify-out/
# Нужны: graph.html, graph.json, GRAPH_REPORT.md, manifest.json, cost.json.
# Они в .gitignore — поэтому не приехали.
```

Можно их **временно** добавить в bundle (просто скопировать `GRAPH_REPORT.md`
текстом — html не критичен, его можно перегенерировать на Mac).

## 6. Самое важное и неочевидное — знания из чатов

Просмотри последние сессии Claude Code по этому проекту:

```bash
ls -la "$HOME/.claude/sessions/" | head -30
ls -la "$HOME/.claude/projects/<slug>/sessions/" 2>/dev/null
```

И составь **summary за всё время работы над проектом** — особенно то,
что **не попало ни в код, ни в Foundation план**:

- Какие решения по **Plan #2 — Booking core** уже обсуждались?
  - Формат команды `/add` (точный синтаксис).
  - UX FSM-wizard'а: какие шаги, какие клавиатуры, какие fallback'и.
  - Гибридный выбор даты/времени — что значит "гибридный" в этом проекте?
  - Обработка конфликтов (что показывать, как разрешать).
  - Списки `/today`, `/tomorrow`, `/week` — формат вывода.
  - История по клиенту — как открывается, что показывает.
- Какие решения по **Plan #3 — Notifications**?
  - Что значит preset `eve_morning` точно? Только дефолт-шаблон или
    что-то большее?
  - Как UI настройки правил выглядит?
  - Сводный дайджест в 09:00 — что в него входит?
- **Plan #4 — Voice intake**:
  - Промпт для GPT-4o-mini (если уже формулировался).
  - Структура output JSON для парсера.
  - Что делать при ambiguity / неполных данных.
- **Plan #5 — Deploy**:
  - Куда планируется деплой (VPS / Fly.io / Railway / своя машина)?
  - Бэкапы SQLite — куда, как часто?
- Любые **отброшенные варианты** и **причины** — это самое ценное, потому
  что иначе я предложу их заново.

# Формат и место сохранения

Создай в репо **один файл**:

```
docs/_transition/transition-bundle.md
```

Структура:

````markdown
# Transition bundle (Windows → Mac), 2026-XX-XX

## 1. Spec: swirling-whistling-tulip.md
<полное содержимое — копипаст>

## 2. Other plans / specs
### <имя файла>
<полное содержимое>

## 3. Project memory
### user_*.md
<...>
### feedback_*.md
<...>
### project_*.md
<...>

## 4. Untracked drafts in repo
<пути + содержимое>

## 5. Claude settings & hooks
### .claude/settings*.json
<...>
### post-commit hook
<...>

## 6. GRAPH_REPORT.md
<...>

## 7. Chat knowledge dump (Booking core / Notifications / Voice / Deploy)
### Booking core decisions
- ...
### Notifications decisions
- ...
### Voice intake decisions
- ...
### Deploy decisions
- ...
### Discarded options + reasons
- ...
````

Если в bundle попадают **секреты** (`BOT_TOKEN`, `OWNER_CHAT_ID`,
`OPENAI_API_KEY`, `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`) — заменяй их на
`${PLACEHOLDER}` или `<REDACTED>`. Bundle уйдёт в публичный git.

# Запушить в GitHub

```bash
git add docs/_transition/transition-bundle.md
git commit -m "docs: transition bundle for Mac handoff"
git push
```

После этого можешь сказать "готово, запушено" — на Mac я сделаю `git pull`
и заберу.

# Если что-то не нашлось

Просто отметь в bundle разделом:

```markdown
## NOT FOUND
- swirling-whistling-tulip.md — не нашёл, искал в: <пути>
- ...
```

Без догадок — пустые/отсутствующие куски лучше, чем выдуманные.
