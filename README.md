# BOT_CLAWS_YULIIA

Личный Telegram-бот для учёта записей клиентов с голосовым вводом, гибкими
уведомлениями и хранилищем в SQLite. Один пользователь (whitelist по chat_id).

## Стек

- Python 3.12 + aiogram 3
- SQLAlchemy 2.0 (async) + aiosqlite + Alembic
- Redis 7 (FSM-storage с TTL и восстановлением прерванных flow)
- APScheduler (планирование уведомлений)
- OpenAI Whisper (default) / Yandex SpeechKit — STT через единый интерфейс
- GPT-4o-mini — парсинг распознанной речи в структурированную запись

## Возможности

- **Голосом**: записываешь "запиши Олега завтра в два часа дня" — бот
  расшифровывает, парсит и присылает карточку с подтверждением.
- **Формой**: пошаговый wizard с гибридным выбором даты/времени.
- **Командой**: `/add 2026-05-06 14:30 Олег @oleg_insta маникюр`.
- Списки `/today`, `/tomorrow`, `/week`, история по клиенту.
- Уведомления: дефолт — 20:00 накануне + 09:00 утром (сводный дайджест).
  Гибкая настройка через UI бота.

## Локальный запуск

1. Установить Docker и Docker Compose.
2. Скопировать конфиг и заполнить:
   ```
   cp .env.example .env
   # отредактировать BOT_TOKEN, OWNER_CHAT_ID, OPENAI_API_KEY, …
   ```
3. Запустить:
   ```
   docker compose up --build
   ```
4. В Telegram написать боту `/start`.

Без Docker (для разработки):
```
poetry install
poetry run alembic upgrade head
poetry run python -m src.main
```
(Локально нужен запущенный Redis: `docker run -p 6379:6379 redis:7-alpine`.)

## Деплой на Oracle Cloud Free VM

См. секцию Verification → "Деплой на Oracle Cloud" в
[`docs/specs/`](docs/specs/) (после генерации спецификации).

Кратко:
```
git clone <repo> /opt/bot-claws
cd /opt/bot-claws
cp .env.example .env && nano .env
docker compose up -d
sudo systemctl enable --now bot-claws.service
```

## Безопасность

- Никаких секретов в коде — только в `.env` (в `.gitignore`).
- БД и логи тоже в `.gitignore` — могут содержать персональные данные клиентов.
- Whitelist-middleware пропускает только `OWNER_CHAT_ID`.
- Бот падает на старте, если обязательные ключи не заданы.
- Перед `git push`: `git status` не должен показывать `.env`, `data/`, `*.db`,
  `*.log`, `dump.rdb`.

## Структура

```
src/
├── bot/         aiogram-хендлеры, клавиатуры, FSM, middleware
├── services/    доменная логика: appointments, clients, notifications, voice, parser
├── storage/    SQLAlchemy-модели и миграции
├── config.py   pydantic-settings
└── main.py     bootstrap
```

Полный план — в `C:\Users\CURSEDEVIL\.claude\plans\swirling-whistling-tulip.md`.
