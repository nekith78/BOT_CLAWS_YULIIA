"""Out-of-band alerts to admin Telegram chats.

When something operational breaks (OpenAI quota exhausted, key invalid,
etc.), the master shouldn't be the one debugging — they're a normal user
of the bot. The developer/admin who set up the deploy needs to be told.

`notify_admins` sends a message to every chat ID in
`Settings.admin_chat_ids` (the comma-separated list). When that's empty
it falls back to `OWNER_CHAT_ID` so single-admin deploys still get the
alert.

Failures of the alert path itself are swallowed — if Telegram is down
when we try to alert, there's no point breaking the calling handler too.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot

    from src.config import Settings

log = logging.getLogger(__name__)


def _admin_targets(settings: Settings) -> list[int]:
    """Resolve which chats to send the alert to.
    ADMIN_CHAT_IDS first; falls back to OWNER_CHAT_ID."""
    admin_ids: list[int] = []
    for raw in (settings.admin_chat_ids or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            admin_ids.append(int(raw))
        except ValueError:
            continue
    return admin_ids or [settings.owner_chat_id]


async def notify_admins(bot: Bot, settings: Settings, text: str) -> None:
    """Fan-out an admin alert. Quietly drops the message if Telegram errors."""
    for chat_id in _admin_targets(settings):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            log.exception("admin_alert send failed for chat_id=%s", chat_id)
