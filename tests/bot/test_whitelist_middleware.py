"""WhitelistMiddleware tests — owner gets through, everyone else is silently dropped."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from aiogram.types import Chat, Message, Update, User

from src.bot.middlewares.whitelist import WhitelistMiddleware


def _make_message(user_id: int) -> Update:
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    msg = Message(
        message_id=1,
        date=1700000000,  # type: ignore[arg-type]
        chat=chat,
        from_user=user,
        text="/start",
    )
    return Update(update_id=1, message=msg)


@pytest.mark.asyncio
async def test_owner_passes_through() -> None:
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(owner_chat_id=42)
    update = _make_message(user_id=42)

    result = await mw(handler, update, {})

    handler.assert_awaited_once()
    assert result == "ok"


@pytest.mark.asyncio
async def test_non_owner_is_silently_dropped() -> None:
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(owner_chat_id=42)
    update = _make_message(user_id=999)

    result = await mw(handler, update, {})

    handler.assert_not_awaited()
    assert result is None


@pytest.mark.asyncio
async def test_update_without_user_is_dropped() -> None:
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(owner_chat_id=42)
    update = Update(update_id=1)  # no message

    result = await mw(handler, update, {})

    handler.assert_not_awaited()
    assert result is None
