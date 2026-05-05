"""/start handler test — sends welcome with main menu keyboard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers.start import handle_start


@pytest.mark.asyncio
async def test_start_replies_with_menu() -> None:
    message = MagicMock()
    message.answer = AsyncMock()
    message.from_user = MagicMock(first_name="Юля")

    await handle_start(message)

    message.answer.assert_awaited_once()
    args, kwargs = message.answer.call_args
    text = args[0] if args else kwargs.get("text", "")
    assert "Юля" in text or "Привет" in text
    assert kwargs.get("reply_markup") is not None
