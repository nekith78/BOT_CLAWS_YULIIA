"""Tests for /clients + history with period picker."""

from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.callback_data import PeriodCD
from src.bot.handlers.clients import handle_clients, on_period_picked
from src.services import settings_service
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

TZ = ZoneInfo("Asia/Almaty")


@pytest_asyncio.fixture
async def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=100)
    return FSMContext(storage=storage, key=key)


@pytest_asyncio.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    b.edit_message_text = AsyncMock()
    return b


@pytest_asyncio.fixture
async def session_factory(engine):  # type: ignore[no-untyped-def]
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _msg() -> MagicMock:
    m = MagicMock(spec=Message)
    m.chat = MagicMock(id=100)
    return m


def _cb() -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(chat=MagicMock(id=100))
    cb.answer = AsyncMock()
    return cb


def _utc_naive(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


async def test_clients_empty(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        await session.commit()
    await handle_clients(_msg(), state=state, bot=bot, session_factory=session_factory)
    bot.send_message.assert_awaited_once()
    assert "Клиентов пока нет" in bot.send_message.await_args.kwargs["text"]


async def test_clients_with_recent(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        await ClientRepository(session).create(name="Олег")
        await ClientRepository(session).create(name="Аня")
        await session.commit()
    await handle_clients(_msg(), state=state, bot=bot, session_factory=session_factory)
    payload = bot.send_message.await_args.kwargs
    assert payload["reply_markup"] is not None
    btn_texts = [b.text for row in payload["reply_markup"].inline_keyboard for b in row]
    assert "Олег" in btn_texts and "Аня" in btn_texts


async def test_history_all_returns_grouped_list(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.flush()
        appts = AppointmentRepository(session)
        await appts.create(
            client_id=client.id,
            starts_at=_utc_naive(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
            visit_note="маникюр",
        )
        await appts.create(
            client_id=client.id,
            starts_at=_utc_naive(datetime(2026, 4, 1, 11, 0, tzinfo=TZ)),
        )
        await session.commit()
        client_id = client.id

    cb = _cb()
    pcd = PeriodCD(kind="all", scope="client", scope_id=client_id)
    await on_period_picked(
        cb, callback_data=pcd, state=state, bot=bot, session_factory=session_factory
    )

    edit_args = bot.edit_message_text.await_args
    if edit_args is None:
        # First message — sent fresh
        send_args = bot.send_message.await_args
        text = send_args.kwargs["text"]
        kb = send_args.kwargs["reply_markup"]
    else:
        text = edit_args.kwargs["text"]
        kb = edit_args.kwargs["reply_markup"]
    assert "Олег" in text
    assert "Все записи" in text
    # 2 appointments → 2 inline rows
    assert len(kb.inline_keyboard) == 2


async def test_history_today_when_empty(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.commit()
        client_id = client.id

    cb = _cb()
    pcd = PeriodCD(kind="today", scope="client", scope_id=client_id)
    await on_period_picked(
        cb, callback_data=pcd, state=state, bot=bot, session_factory=session_factory
    )
    text = (bot.edit_message_text.await_args or bot.send_message.await_args).kwargs["text"]
    assert "Записей нет" in text


# Used to silence unused-import warnings for `time`.
_ = time
