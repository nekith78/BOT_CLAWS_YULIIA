"""Whitelist middleware — drops every update from non-allowed users.

Silent drop (no reply) — это намеренно: бот не должен подтверждать своё
существование чужим пользователям.

Accepts a set of allowed chat IDs so the bot can have multiple admins
(typically: the master who uses the bot day-to-day + the developer who
maintains it). Backwards-compatible: passing a single int wraps it in a
one-element set.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

log = logging.getLogger(__name__)


class WhitelistMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        owner_chat_id: int | None = None,
        allowed_chat_ids: set[int] | None = None,
    ) -> None:
        super().__init__()
        if allowed_chat_ids is None:
            if owner_chat_id is None:
                raise ValueError(
                    "WhitelistMiddleware needs owner_chat_id or allowed_chat_ids"
                )
            allowed_chat_ids = {owner_chat_id}
        elif owner_chat_id is not None:
            allowed_chat_ids = allowed_chat_ids | {owner_chat_id}
        self._allowed: set[int] = allowed_chat_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id = self._extract_user_id(event)
        if user_id is None:
            log.debug("dropping update without user: %r", type(event).__name__)
            return None
        if user_id not in self._allowed:
            log.warning("unauthorized access attempt: user_id=%s", user_id)
            return None
        return await handler(event, data)

    @staticmethod
    def _extract_user_id(event: TelegramObject) -> int | None:
        if isinstance(event, Update):
            for candidate in (
                event.message,
                event.edited_message,
                event.callback_query,
                event.inline_query,
                event.chosen_inline_result,
                event.my_chat_member,
                event.chat_member,
                event.shipping_query,
                event.pre_checkout_query,
                event.poll_answer,
            ):
                if candidate is not None and getattr(candidate, "from_user", None) is not None:
                    return candidate.from_user.id  # type: ignore[union-attr]
            return None
        from_user = getattr(event, "from_user", None)
        return from_user.id if from_user is not None else None
