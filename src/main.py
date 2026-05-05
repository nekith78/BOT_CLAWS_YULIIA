"""Bot bootstrap.

Startup pipeline:
1. Load config (validates env)
2. Configure logging
3. Build async DB engine
4. Run pending Alembic migrations programmatically
   (skipped here — handled by docker-compose entrypoint)
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
