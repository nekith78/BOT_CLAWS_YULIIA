"""Bot bootstrap.

Startup pipeline:
1. Load config (validates env)
2. Configure logging
3. Build async DB engine + session factory (single instance for lifetime)
4. Run pending Alembic migrations programmatically
   (skipped here — handled by docker-compose entrypoint)
5. Seed defaults (idempotent)
6. Build APScheduler + recovery for missed notifications
7. Build dispatcher: Redis FSM storage + WhitelistMiddleware +
   ConcurrencyMiddleware on callback_query + all routers
8. Start polling
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.bot.handlers import (
    add_appointment as add_appt_handlers,
)
from src.bot.handlers import (
    appointment_card as appt_card_handlers,
)
from src.bot.handlers import (
    clients as clients_handlers,
)
from src.bot.handlers import (
    dev_panel as dev_panel_handlers,  # TEMP: remove with the file when done debugging
)
from src.bot.handlers import (
    lists as lists_handlers,
)
from src.bot.handlers import (
    notify_settings as notify_settings_handlers,
)
from src.bot.handlers import (
    start as start_handlers,
)
from src.bot.handlers import (
    system as system_handlers,
)
from src.bot.handlers import (
    text_add as text_add_handlers,
)
from src.bot.middlewares.concurrency import ConcurrencyMiddleware
from src.bot.middlewares.whitelist import WhitelistMiddleware
from src.config import Settings, ensure_data_dir, load_settings
from src.services import settings_service
from src.services.notifications.scheduler import (
    build_scheduler,
    make_job_runner,
    recover_missed_jobs,
)
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


async def _seed_defaults(factory: async_sessionmaker[AsyncSession]) -> None:
    async with db.session_scope(factory) as session:
        await settings_service.seed_defaults(session)


def _build_dispatcher(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    scheduler: AsyncIOScheduler,
    notify_runner: Any,
) -> Dispatcher:
    storage = RedisStorage.from_url(
        settings.redis_url,
        state_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
        data_ttl=timedelta(minutes=settings.fsm_ttl_minutes),
    )
    dp = Dispatcher(storage=storage)

    # Make session factory + notification deps available to handlers as kwargs.
    dp["session_factory"] = session_factory
    dp["scheduler"] = scheduler
    dp["notify_runner"] = notify_runner

    # Whitelist must run before any router so unauthorised updates never reach handlers.
    dp.update.outer_middleware(WhitelistMiddleware(owner_chat_id=settings.owner_chat_id))
    # Drop double-tap clicks on the same message id.
    dp.callback_query.middleware(ConcurrencyMiddleware())

    # Order matters: system has the highest priority so /cancel always wins.
    dp.include_router(system_handlers.router)
    dp.include_router(dev_panel_handlers.router)  # TEMP debug panel
    dp.include_router(start_handlers.router)
    dp.include_router(add_appt_handlers.router)
    dp.include_router(text_add_handlers.router)
    dp.include_router(lists_handlers.router)
    dp.include_router(clients_handlers.router)
    dp.include_router(notify_settings_handlers.router)
    dp.include_router(appt_card_handlers.router)
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

    engine: AsyncEngine = db.create_engine(settings.db_url)
    session_factory = db.create_session_factory(engine)
    try:
        await _seed_defaults(session_factory)

        bot = Bot(
            token=settings.bot_token.get_secret_value(),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

        scheduler = build_scheduler(settings.db_url)
        scheduler.start()
        notify_runner = make_job_runner(
            bot=bot,
            session_factory=session_factory,
            owner_chat_id=settings.owner_chat_id,
        )

        try:
            # Catch up on notifications missed while the bot was offline.
            async with db.session_scope(session_factory) as session:
                tz = await settings_service.get_timezone(session)
                now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
                sent_late, skipped = await recover_missed_jobs(
                    session,
                    bot=bot,
                    owner_chat_id=settings.owner_chat_id,
                    tz=tz,
                    now_utc=now_utc,
                )
            log.info(
                "notification recovery: sent_late=%s skipped=%s",
                sent_late, skipped,
            )

            dp = _build_dispatcher(
                settings, session_factory, scheduler, notify_runner
            )
            await dp.start_polling(
                bot, allowed_updates=dp.resolve_used_update_types()
            )
        finally:
            scheduler.shutdown(wait=False)
            await bot.session.close()
    finally:
        await engine.dispose()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
