"""System handlers: /cancel, /help, global error fallback.

Registered FIRST in main dispatcher so /cancel beats every FSM router.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.bot.callback_data import SettingsCD
from src.bot.ui import cancel as ui_cancel

log = logging.getLogger(__name__)
router = Router(name="system")

HELP_TEXT = (
    "<b>Команды</b>\n"
    "• /new — мастер создания записи (или кнопка «+ Запись»)\n"
    "• /add YYYY-MM-DD HH:MM Имя [@инста] [заметка] — быстрая запись\n"
    "• /today, /tomorrow, /week — списки\n"
    "• /clients — клиенты + история\n"
    "• /cancel — прервать текущий мастер\n"
    "• /help — эта справка"
)


@router.message(Command("cancel"))
async def handle_cancel(message: Message, state: FSMContext, bot: Bot) -> None:
    current = await state.get_state()
    if current is None:
        await bot.send_message(chat_id=message.chat.id, text="Сейчас нет активного мастера.")
        return
    await ui_cancel(bot, chat_id=message.chat.id, state=state)


@router.message(Command("help"))
async def handle_help(message: Message, bot: Bot) -> None:
    await bot.send_message(chat_id=message.chat.id, text=HELP_TEXT)


@router.message(F.text == "⚙️ Настройки")
async def handle_settings_menu(message: Message, bot: Bot) -> None:
    """Top-level settings menu. Currently exposes notifications only;
    timezone editor and others are stubs for later plans."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔔 Настройка уведомлений",
                    callback_data=SettingsCD(action="notifications").pack(),
                )
            ],
        ]
    )
    await bot.send_message(
        chat_id=message.chat.id,
        text="⚙️ Настройки\n\nВыбери раздел:",
        reply_markup=kb,
    )


@router.errors()
async def on_error(event: ErrorEvent, **data: Any) -> None:
    """Global error fallback. Logs and replies to the originating chat if possible."""
    log.exception("unhandled error: %s", event.exception, exc_info=event.exception)
    update = event.update
    chat_id: int | None = None
    if update.message is not None and update.message.chat is not None:
        chat_id = update.message.chat.id
    elif update.callback_query is not None and update.callback_query.message is not None:
        msg = update.callback_query.message
        chat_id = msg.chat.id if hasattr(msg, "chat") else None

    bot = data.get("bot")
    if chat_id is None or bot is None:
        return
    try:
        await bot.send_message(chat_id=chat_id, text="⚠️ Что-то пошло не так. Попробуй ещё раз.")
    except Exception as exc:
        log.error("error reply failed: %s", exc)

    state = data.get("state")
    if state is not None:
        try:
            await state.clear()
        except Exception as exc:
            log.error("state.clear() in error handler failed: %s", exc)
