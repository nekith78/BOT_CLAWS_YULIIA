"""ui helpers — edit existing message OR send new, then chain."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from src.bot.ui import advance, cancel, finalize


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


async def test_advance_sends_first_message_and_stores_id(
    bot: MagicMock, state: FSMContext
) -> None:
    await advance(bot, chat_id=100, state=state, text="step 1", reply_markup=None)
    bot.send_message.assert_awaited_once()
    data = await state.get_data()
    assert data["flow_message_id"] == 555


async def test_advance_edits_existing_flow_message(
    bot: MagicMock, state: FSMContext
) -> None:
    await state.update_data(flow_message_id=999)
    await advance(bot, chat_id=100, state=state, text="step 2", reply_markup=None)
    bot.edit_message_text.assert_awaited_once()
    bot.send_message.assert_not_awaited()


async def test_finalize_strips_keyboard_and_clears_state(
    bot: MagicMock, state: FSMContext
) -> None:
    await state.update_data(flow_message_id=999, draft={"x": 1})
    await finalize(bot, chat_id=100, state=state, text="✅ saved")
    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs.get("reply_markup") is None
    assert await state.get_state() is None


async def test_finalize_without_flow_message_sends_plain(
    bot: MagicMock, state: FSMContext
) -> None:
    await finalize(bot, chat_id=100, state=state, text="✅ saved")
    bot.send_message.assert_awaited_once()
    bot.edit_message_text.assert_not_awaited()


async def test_cancel_sends_cancel_text_and_clears_state(
    bot: MagicMock, state: FSMContext
) -> None:
    await state.update_data(flow_message_id=999)
    await cancel(bot, chat_id=100, state=state)
    bot.edit_message_text.assert_awaited_once()
    assert "Отмен" in bot.edit_message_text.await_args.kwargs["text"]
    assert await state.get_state() is None
