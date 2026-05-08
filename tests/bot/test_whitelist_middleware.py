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


@pytest.mark.asyncio
async def test_multiple_allowed_chat_ids() -> None:
    """Plan #7 — set-based init lets the bot have multiple admins
    (e.g. master + developer)."""
    handler = AsyncMock(return_value="ok")
    mw = WhitelistMiddleware(allowed_chat_ids={42, 999})

    # Both admins pass through.
    assert await mw(handler, _make_message(user_id=42), {}) == "ok"
    assert await mw(handler, _make_message(user_id=999), {}) == "ok"
    # Random outsider still dropped.
    assert await mw(handler, _make_message(user_id=12345), {}) is None
    assert handler.await_count == 2


def test_whitelist_chat_ids_property_parses_admin_list() -> None:
    """Settings.whitelist_chat_ids merges owner + comma-separated admins."""
    from src.config import Settings

    s = Settings(
        bot_token="x",  # type: ignore[arg-type]
        owner_chat_id=100,
        admin_chat_ids="200, 300, garbage, 400",
        openrouter_api_key="x",  # type: ignore[arg-type]
    )
    assert s.whitelist_chat_ids == {100, 200, 300, 400}


def test_whitelist_chat_ids_when_no_admins() -> None:
    from src.config import Settings

    s = Settings(
        bot_token="x",  # type: ignore[arg-type]
        owner_chat_id=100,
        openrouter_api_key="x",  # type: ignore[arg-type]
    )
    assert s.whitelist_chat_ids == {100}
