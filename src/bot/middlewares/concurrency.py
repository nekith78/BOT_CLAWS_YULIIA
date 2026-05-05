"""In-memory lock per (chat_id, message_id) for CallbackQuery double-tap protection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject


class ConcurrencyMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self._busy: set[tuple[int, int]] = set()
        self._lock = asyncio.Lock()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery) or event.message is None:
            return await handler(event, data)
        key = (event.message.chat.id, event.message.message_id)
        async with self._lock:
            if key in self._busy:
                await event.answer()
                return None
            self._busy.add(key)
        try:
            return await handler(event, data)
        finally:
            async with self._lock:
                self._busy.discard(key)
