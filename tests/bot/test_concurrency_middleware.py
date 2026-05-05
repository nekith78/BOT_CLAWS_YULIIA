"""ConcurrencyMiddleware drops second click on the same (chat_id, message_id)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery

from src.bot.middlewares.concurrency import ConcurrencyMiddleware


def _make_callback(chat_id: int, message_id: int) -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(chat=MagicMock(id=chat_id), message_id=message_id)
    cb.answer = AsyncMock()
    return cb


async def test_first_click_passes_through() -> None:
    mw = ConcurrencyMiddleware()
    handler = AsyncMock(return_value="ok")
    cb = _make_callback(1, 100)
    result = await mw(handler, cb, {})
    assert result == "ok"
    handler.assert_awaited_once()


async def test_second_click_during_handler_is_dropped() -> None:
    mw = ConcurrencyMiddleware()

    async def slow_handler(_event: Any, _data: dict[str, Any]) -> str:
        await asyncio.sleep(0.05)
        return "done"

    cb1 = _make_callback(1, 100)
    cb2 = _make_callback(1, 100)
    task1 = asyncio.create_task(mw(slow_handler, cb1, {}))
    await asyncio.sleep(0.01)
    result2 = await mw(slow_handler, cb2, {})
    result1 = await task1
    assert result1 == "done"
    assert result2 is None
    cb2.answer.assert_awaited_once()


async def test_different_messages_do_not_block() -> None:
    mw = ConcurrencyMiddleware()
    handler = AsyncMock(return_value="ok")
    r1 = await mw(handler, _make_callback(1, 100), {})
    r2 = await mw(handler, _make_callback(1, 101), {})
    assert r1 == "ok" and r2 == "ok"
    assert handler.await_count == 2


async def test_lock_released_on_handler_exception() -> None:
    """After a handler raises, the lock must be released so retries work."""
    mw = ConcurrencyMiddleware()

    async def boom(_event: Any, _data: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    cb = _make_callback(1, 100)
    try:
        await mw(boom, cb, {})
    except RuntimeError:
        pass

    handler = AsyncMock(return_value="ok")
    result = await mw(handler, _make_callback(1, 100), {})
    assert result == "ok"


async def test_non_callback_query_passes_through() -> None:
    """Non-CallbackQuery events bypass the lock."""
    mw = ConcurrencyMiddleware()
    handler = AsyncMock(return_value="ok")
    message = MagicMock()
    result = await mw(handler, message, {})
    assert result == "ok"
