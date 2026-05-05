"""Bot bootstrap.

Минимальный скаффолд: загружает конфиг, поднимает aiogram + Redis-FSM,
регистрирует пустой dispatcher и запускает long polling.

Логика хендлеров, БД, scheduler'а, голосового ввода и уведомлений
добавляется в последующих этапах (см. plan, шаги 2-16).
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

from src.config import Settings, ensure_data_dir, load_settings


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Шум от httpx/aiogram-внутренностей сбавляем
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram.event").setLevel(logging.INFO)


async def _build_dispatcher(settings: Settings) -> Dispatcher:
    storage = RedisStorage.from_url(
        settings.redis_url,
        state_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
        data_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
    )
    dp = Dispatcher(storage=storage)
    # Хендлеры регистрируются в следующих этапах:
    # from src.bot.handlers import start, ...
    # dp.include_router(start.router)
    return dp


async def run() -> None:
    settings = load_settings()
    _configure_logging(settings.log_level)
    ensure_data_dir(settings)

    log = logging.getLogger("bot")
    log.info("Starting bot, owner=%s tz=%s stt=%s",
             settings.owner_chat_id, settings.owner_tz, settings.stt_provider)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = await _build_dispatcher(settings)

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
