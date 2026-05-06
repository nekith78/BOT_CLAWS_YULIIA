"""Tests for /cancel, /help, error fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from src.bot.handlers.system import HELP_TEXT, handle_cancel, handle_help
from src.bot.states import AddAppointment


@pytest_asyncio.fixture
async def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=100)
    return FSMContext(storage=storage, key=key)


@pytest_asyncio.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock()
    b.edit_message_text = AsyncMock()
    return b


def _msg() -> MagicMock:
    m = MagicMock(spec=Message)
    m.chat = MagicMock(id=100)
    return m


async def test_cancel_without_state_replies_no_active_wizard(
    state: FSMContext, bot: MagicMock
) -> None:
    await handle_cancel(_msg(), state=state, bot=bot)
    bot.send_message.assert_awaited_once()
    assert "нет активного" in bot.send_message.await_args.kwargs["text"]


async def test_cancel_in_state_clears_and_finalizes(
    state: FSMContext, bot: MagicMock
) -> None:
    await state.set_state(AddAppointment.choosing_client)
    await state.update_data(flow_message_id=999)
    await handle_cancel(_msg(), state=state, bot=bot)
    assert await state.get_state() is None
    bot.edit_message_text.assert_awaited_once()
    assert "Отмен" in bot.edit_message_text.await_args.kwargs["text"]


async def test_help_replies_with_command_list(bot: MagicMock) -> None:
    await handle_help(_msg(), bot=bot)
    payload = bot.send_message.await_args.kwargs
    assert payload["text"] == HELP_TEXT
    assert "/add" in payload["text"]
    assert "/today" in payload["text"]
    assert "/clients" in payload["text"]
