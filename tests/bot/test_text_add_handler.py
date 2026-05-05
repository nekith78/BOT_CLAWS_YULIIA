"""Tests for /add command handler — parse → state setup → confirm card."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers.text_add import handle_add
from src.bot.states import AddAppointment
from src.storage.repositories.clients import ClientRepository


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


def _make_message() -> MagicMock:
    m = MagicMock(spec=Message)
    m.chat = MagicMock(id=100)
    return m


async def test_invalid_input_replies_with_usage(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cmd = CommandObject(command="add", args="не команда")
    await handle_add(_make_message(), cmd, state=state, bot=bot, session_factory=session_factory)
    bot.send_message.assert_awaited_once()
    assert "Формат" in bot.send_message.await_args.kwargs["text"]
    assert await state.get_state() is None


async def test_no_args_replies_with_usage(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cmd = CommandObject(command="add", args=None)
    await handle_add(_make_message(), cmd, state=state, bot=bot, session_factory=session_factory)
    bot.send_message.assert_awaited_once()
    assert await state.get_state() is None


async def test_valid_creates_client_and_shows_confirm(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cmd = CommandObject(
        command="add", args="2026-05-06 14:30 Олег @oleg маникюр"
    )
    await handle_add(_make_message(), cmd, state=state, bot=bot, session_factory=session_factory)

    # Карточка ушла через send_message (flow_message_id ещё не было).
    bot.send_message.assert_awaited_once()
    payload = bot.send_message.await_args.kwargs
    assert "Олег" in payload["text"]
    assert "маникюр" in payload["text"]
    assert payload["reply_markup"] is not None

    assert await state.get_state() == AddAppointment.confirming.state
    data = await state.get_data()
    assert data["picked_date"] == "2026-05-06"
    assert data["picked_time"] == "14:30"
    assert data["visit_note"] == "маникюр"

    # Клиент должен был быть создан.
    async with session_factory() as session:
        clients = await ClientRepository(session).list_recent()
    assert any(c.name == "Олег" and c.instagram == "oleg" for c in clients)


async def test_valid_reuses_existing_client_case_insensitive(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        existing = await ClientRepository(session).create(name="ОЛЕГ", instagram="legacy")
        await session.commit()
        existing_id = existing.id

    cmd = CommandObject(command="add", args="2026-05-06 14:00 олег маникюр")
    await handle_add(_make_message(), cmd, state=state, bot=bot, session_factory=session_factory)

    data = await state.get_data()
    assert data["client_id"] == existing_id  # переиспользован, не создан новый

    async with session_factory() as session:
        clients = await ClientRepository(session).list_recent()
    assert sum(1 for c in clients if c.name.lower() == "олег") == 1
