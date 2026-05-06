"""Single active FSM message helpers — edit-in-place vs send-new."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)
CANCELLED_TEXT = "❌ Отменено"


async def show_in_callback(
    callback: CallbackQuery,
    *,
    bot: Bot,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    """Edit the message the user clicked, or send a new one if edit fails.

    Use this for *view-only* handlers (open card, show history) that must NOT
    touch the wizard's flow_message_id. The edit hits exactly the message the
    button lived on, so an active wizard in the same chat is unaffected.
    """
    msg = callback.message
    if isinstance(msg, Message):
        try:
            await msg.edit_text(text=text, reply_markup=reply_markup)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
            log.warning("show_in_callback edit failed (%s); sending new", exc)
    if msg is not None:
        await bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=reply_markup)


async def advance(
    bot: Bot,
    *,
    chat_id: int,
    state: FSMContext,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    """Edit `flow_message_id` if present, else send a new message and store its id."""
    data = await state.get_data()
    flow_id = data.get("flow_message_id")
    if flow_id is None:
        msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        await state.update_data(flow_message_id=msg.message_id)
        return
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=flow_id,
            text=text,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return
        log.warning("flow message edit failed (%s); sending new", exc)
        msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        await state.update_data(flow_message_id=msg.message_id)


async def finalize(bot: Bot, *, chat_id: int, state: FSMContext, text: str) -> None:
    """Replace flow message with final text, drop the keyboard, clear state."""
    data = await state.get_data()
    flow_id = data.get("flow_message_id")
    if flow_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=flow_id,
                text=text,
                reply_markup=None,
            )
        except TelegramBadRequest as exc:
            log.warning("finalize edit failed (%s); sending plain", exc)
            await bot.send_message(chat_id=chat_id, text=text)
    else:
        await bot.send_message(chat_id=chat_id, text=text)
    await state.clear()


async def cancel(bot: Bot, *, chat_id: int, state: FSMContext) -> None:
    """Cancel current flow with a fixed `❌ Отменено` line."""
    await finalize(bot, chat_id=chat_id, state=state, text=CANCELLED_TEXT)
