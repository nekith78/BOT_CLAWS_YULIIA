"""Format and send notification messages to the owner."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from src.storage.models import Appointment, Client

log = logging.getLogger(__name__)

LATE_PREFIX = "⏰ (с задержкой) "


def _e(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _hhmm(appt: Appointment, *, tz: ZoneInfo) -> str:
    local = appt.starts_at.replace(tzinfo=timezone.utc).astimezone(tz)
    return local.strftime("%H:%M")


def format_eve_digest(
    pairs: list[tuple[Appointment, Client]], *, tz: ZoneInfo, late: bool = False
) -> str:
    prefix = LATE_PREFIX if late else ""
    if not pairs:
        return f"{prefix}🔔 На завтра записей нет."
    n = len(pairs)
    head = f"{prefix}🔔 Завтра {n} запис" + (
        "ь:" if n == 1 else ("и:" if 2 <= n <= 4 else "ей:")
    )
    rows = sorted(pairs, key=lambda p: p[0].starts_at)
    lines = [head]
    for appt, client in rows:
        note = f" · {_e(appt.visit_note)}" if appt.visit_note else ""
        lines.append(f"{_hhmm(appt, tz=tz)} · {_e(client.name)}{note}")
    return "\n".join(lines)


def format_offset_ping(
    appt: Appointment, client: Client, *, tz: ZoneInfo, late: bool = False
) -> str:
    prefix = LATE_PREFIX if late else ""
    note = f" · {_e(appt.visit_note)}" if appt.visit_note else ""
    return (
        f"{prefix}⏰ Через час: {_hhmm(appt, tz=tz)} · "
        f"{_e(client.name)}{note}"
    )


async def send_eve_digest(
    bot: Bot,
    chat_id: int,
    pairs: list[tuple[Appointment, Client]],
    *,
    tz: ZoneInfo,
    late: bool = False,
) -> None:
    text = format_eve_digest(pairs, tz=tz, late=late)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        log.warning("send_eve_digest failed: %s", exc)


async def send_offset_ping(
    bot: Bot,
    chat_id: int,
    appt: Appointment,
    client: Client,
    *,
    tz: ZoneInfo,
    late: bool = False,
) -> None:
    text = format_offset_ping(appt, client, tz=tz, late=late)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        log.warning("send_offset_ping failed: %s", exc)


# Used to silence unused-import warning for datetime when wiring fails.
_ = datetime
