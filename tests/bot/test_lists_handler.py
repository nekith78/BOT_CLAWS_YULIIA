"""Tests for /today /tomorrow /week handlers."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest_asyncio
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers.lists import handle_today, handle_tomorrow, handle_week
from src.services import settings_service
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

TZ = ZoneInfo("Asia/Almaty")


@pytest_asyncio.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock()
    return b


@pytest_asyncio.fixture
async def session_factory(engine):  # type: ignore[no-untyped-def]
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _msg() -> MagicMock:
    m = MagicMock(spec=Message)
    m.chat = MagicMock(id=100)
    return m


def _utc_naive_local(local_dt: datetime) -> datetime:
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


async def test_today_empty(
    bot: MagicMock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        await session.commit()

    await handle_today(_msg(), bot=bot, session_factory=session_factory)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs["text"].lower()
    assert "сегодня" in text
    assert "записей нет" in text


async def test_today_with_two_appointments(
    bot: MagicMock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.flush()
        today_local = datetime.now(tz=TZ).date()
        await AppointmentRepository(session).create(
            client_id=client.id,
            starts_at=_utc_naive_local(datetime.combine(today_local, time(11, 0), tzinfo=TZ)),
            duration_min=60,
            visit_note="маникюр",
        )
        await AppointmentRepository(session).create(
            client_id=client.id,
            starts_at=_utc_naive_local(datetime.combine(today_local, time(15, 0), tzinfo=TZ)),
            duration_min=60,
        )
        await session.commit()

    await handle_today(_msg(), bot=bot, session_factory=session_factory)

    payload = bot.send_message.await_args.kwargs
    assert payload["reply_markup"] is not None
    btn_texts = [b.text for row in payload["reply_markup"].inline_keyboard for b in row]
    # Должно быть 2 кнопки в формате "HH:MM · Олег..."
    assert sum(1 for t in btn_texts if t.startswith("11:00")) == 1
    assert sum(1 for t in btn_texts if t.startswith("15:00")) == 1
    # Заметка прикреплена в первой
    assert any("маникюр" in t for t in btn_texts)


async def test_tomorrow_label(
    bot: MagicMock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        await session.commit()
    await handle_tomorrow(_msg(), bot=bot, session_factory=session_factory)
    assert "завтра" in bot.send_message.await_args.kwargs["text"].lower()


async def test_week_groups_by_day(
    bot: MagicMock, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Аня")
        await session.flush()
        today_local = datetime.now(tz=TZ).date()
        # 1 запись сегодня, 1 послезавтра
        await AppointmentRepository(session).create(
            client_id=client.id,
            starts_at=_utc_naive_local(datetime.combine(today_local, time(9, 0), tzinfo=TZ)),
            duration_min=60,
        )
        await AppointmentRepository(session).create(
            client_id=client.id,
            starts_at=_utc_naive_local(
                datetime.combine(today_local + timedelta(days=2), time(13, 0), tzinfo=TZ)
            ),
            duration_min=60,
        )
        await session.commit()

    await handle_week(_msg(), bot=bot, session_factory=session_factory)
    payload = bot.send_message.await_args.kwargs
    text = payload["text"]
    # Заголовок "🗓 Неделя:" + 2 заголовка дней (числа разные)
    assert "Неделя" in text
    # Inline-rows = 2 (по одной на запись)
    rows = payload["reply_markup"].inline_keyboard
    assert len(rows) == 2
