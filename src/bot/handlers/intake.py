"""Voice / free-text intake handler.

Single entry point for two kinds of incoming messages:
- `F.voice` — Telegram voice note → STT → LLM parser → Action dispatch.
- `F.text` (without slash-command and not a known reply-text-button) →
  same path skipping STT.

Wired LAST in `main.py` so reserved reply-text buttons («+ Запись»,
«📋 Записи» etc.) keep their dedicated handlers.

If the user is mid-FSM when a voice/text command arrives, the active
wizard is finalised with «❌ Отменено» first — voice always interrupts.
"""

from __future__ import annotations

import io
import logging
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.callback_data import IntakeCD
from src.bot.keyboards.confirm_card import confirm_card_kb
from src.bot.states import IntakePending
from src.bot.ui import cancel as ui_cancel
from src.services import settings_service
from src.services.intent import build_system_prompt
from src.services.intent.actions import register_default_actions
from src.services.intent.registry import default_registry
from src.services.intent.types import (
    Action,
    ActionContext,
    ActionResponse,
    ActionResult,
)
from src.services.voice.stt import STTProvider
from src.storage.db import session_scope

log = logging.getLogger(__name__)
router = Router(name="intake")


# Reserved reply-text labels that have their own handlers — intake skips these.
_RESERVED_TEXT_BUTTONS = {
    "+ Запись",
    "📋 Записи",
    "👥 Клиенты",
    "⚙️ Настройки",
}


# In-memory short-term conversational history keyed by chat_id — last 3
# user turns. A turn = `{user_text, tool_name, args, snapshot, timestamp}`.
# Replayed into the system prompt so the LLM can resolve follow-ups like
# «удали эту запись», «отмени последнюю». Per-turn TTL 10 min; bot restart
# wipes the deque (acceptable — context is conversational not durable).
_RECENT_TURNS_MAX = 3
_RECENT_TURNS_TTL_SEC = 600
_RECENT_TURNS: dict[int, deque[dict[str, Any]]] = {}


def _push_turn(chat_id: int, turn: dict[str, Any]) -> None:
    queue = _RECENT_TURNS.setdefault(
        chat_id, deque(maxlen=_RECENT_TURNS_MAX)
    )
    queue.append(turn)


def _get_recent_turns(chat_id: int) -> list[dict[str, Any]]:
    queue = _RECENT_TURNS.get(chat_id)
    if not queue:
        return []
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=_RECENT_TURNS_TTL_SEC)
    fresh = [t for t in queue if t.get("timestamp") and t["timestamp"] >= cutoff]
    if len(fresh) != len(queue):
        # Drop stale entries from the head.
        queue.clear()
        for t in fresh:
            queue.append(t)
    return list(queue)


def _clear_recent(chat_id: int) -> None:
    _RECENT_TURNS.pop(chat_id, None)


# Lazy registry init — first import.
_REGISTRY_READY = False


def _ensure_registry() -> Any:
    global _REGISTRY_READY
    reg = default_registry()
    if not _REGISTRY_READY:
        register_default_actions(reg)
        _REGISTRY_READY = True
    return reg


# ---------- entry: voice -----------------------------------------------------


@router.message(F.voice)
async def on_voice(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    if message.voice is None or message.from_user is None:
        return
    settings = data.get("settings")
    stt: STTProvider | None = data.get("stt")
    if stt is None or settings is None:
        log.error("intake: voice received but STT/settings not in dispatcher data")
        return

    chat_id = message.chat.id
    duration = message.voice.duration or 0
    if duration > settings.voice_max_duration_sec:
        await bot.send_message(
            chat_id=chat_id,
            text=f"Слишком длинное сообщение — до {settings.voice_max_duration_sec} сек.",
        )
        return

    # Cancel any active wizard before showing the status — keeps message order
    # natural (cancel ack first, then "обрабатываю").
    await _cancel_active_state(bot=bot, state=state, chat_id=chat_id)

    status_msg_id = await _send_status(bot, chat_id, "⏳ Распознаю голос…")

    # Download voice as bytes.
    file = await bot.get_file(message.voice.file_id)
    if file.file_path is None:
        await _replace_status(bot, chat_id, status_msg_id, "Не удалось скачать голосовое.")
        return
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    audio = buf.getvalue()

    transcript = await stt.transcribe(audio, mime="audio/ogg")
    if not transcript.strip():
        await _replace_status(
            bot, chat_id, status_msg_id, "Не услышал ничего. Попробуй ещё раз."
        )
        return

    log.info("intake voice → transcript: %r", transcript)
    await _edit_status(bot, chat_id, status_msg_id, "⏳ Обрабатываю команду…")
    await _dispatch(
        message=message,
        state=state,
        bot=bot,
        transcript=transcript,
        data=data,
        status_msg_id=status_msg_id,
    )


# ---------- entry: free text -------------------------------------------------


@router.message(
    F.text
    & ~F.text.startswith("/")
    & ~F.text.in_(_RESERVED_TEXT_BUTTONS)
)
async def on_text(message: Message, state: FSMContext, bot: Bot, **data: Any) -> None:
    if message.text is None:
        return
    text = message.text.strip()
    if not text:
        return
    chat_id = message.chat.id
    await _cancel_active_state(bot=bot, state=state, chat_id=chat_id)
    status_msg_id = await _send_status(bot, chat_id, "⏳ Обрабатываю команду…")
    await _dispatch(
        message=message,
        state=state,
        bot=bot,
        transcript=text,
        data=data,
        status_msg_id=status_msg_id,
    )


# ---------- status-message helpers -------------------------------------------


async def _send_status(bot: Bot, chat_id: int, text: str) -> int:
    msg = await bot.send_message(chat_id, text)
    return msg.message_id


async def _edit_status(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    """Update the status text in place. Errors swallowed — the worst case is
    the user sees the previous status text for an extra second."""
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
    except TelegramBadRequest as exc:
        log.debug("intake: edit_status failed: %s", exc)


async def _replace_status(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> int:
    """Replace the status message with a final response. Falls back to
    delete + send-new if Telegram refuses the edit. Returns the resulting
    message id (same id on edit, new id on fallback)."""
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
        )
        return message_id
    except TelegramBadRequest as exc:
        log.debug("intake: replace_status edit failed (%s); falling back", exc)
        try:
            await bot.delete_message(chat_id, message_id)
        except TelegramBadRequest:
            pass
        msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
        return msg.message_id


async def _cancel_active_state(*, bot: Bot, state: FSMContext, chat_id: int) -> None:
    """If the user is mid-FSM, finalise with «❌ Отменено» before intake takes over."""
    cur_state = await state.get_state()
    if cur_state is not None:
        await ui_cancel(bot, chat_id=chat_id, state=state)


# ---------- common dispatch --------------------------------------------------


async def _dispatch(
    *,
    message: Message,
    state: FSMContext,
    bot: Bot,
    transcript: str,
    data: dict[str, Any],
    status_msg_id: int,
) -> None:
    chat_id = message.chat.id

    factory = cast(async_sessionmaker[Any], data["session_factory"])
    settings = data["settings"]
    llm = data["llm"]
    scheduler = data.get("scheduler")
    notify_runner = data.get("notify_runner")

    registry = _ensure_registry()
    tools = registry.tool_specs()

    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        now_local = datetime.now(tz=tz)
        now_utc = now_local.astimezone(timezone.utc).replace(tzinfo=None)
        prompt = build_system_prompt(
            now_local=now_local,
            tz=settings.owner_tz,
            recent_turns=_get_recent_turns(chat_id),
        )

        try:
            parsed = await llm.parse_intent(
                text=transcript,
                tools=tools,
                system=prompt,
                now_local=now_local,
            )
        except Exception as exc:
            log.exception("intake: LLM parse failed")
            err_text = _llm_error_text(exc)
            await _replace_status(bot, chat_id, status_msg_id, err_text)
            return

        if parsed.tool_name is None:
            await _replace_status(bot, chat_id, status_msg_id, _help_text())
            return

        action = registry.get(parsed.tool_name)
        if action is None:
            log.warning("intake: LLM picked unknown tool %s", parsed.tool_name)
            await _replace_status(bot, chat_id, status_msg_id, _help_text())
            return

        ctx = ActionContext(
            session=session,
            bot=bot,
            chat_id=chat_id,
            state=state,
            scheduler=scheduler,
            notify_runner=notify_runner,
            tz=tz,
            now_utc=now_utc,
        )
        response = await action.plan(ctx, parsed.args)

    # Record this turn before rendering — even FAIL/CONFIRM responses are
    # part of the conversation history the LLM should see next time.
    _push_turn(
        chat_id,
        {
            "user_text": transcript,
            "tool_name": parsed.tool_name,
            "args": dict(parsed.args),
            "snapshot": response.context_snapshot,
            "timestamp": datetime.now(tz=timezone.utc),
        },
    )

    # Render outside the session — render needs no DB.
    await _render(
        bot=bot,
        chat_id=chat_id,
        state=state,
        action=action,
        args=parsed.args,
        response=response,
        status_msg_id=status_msg_id,
    )


async def _render(
    *,
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    action: Action,
    args: dict[str, Any],
    response: ActionResponse,
    status_msg_id: int,
) -> None:
    if response.result is ActionResult.EXECUTED:
        await _replace_status(
            bot, chat_id, status_msg_id, response.text,
            reply_markup=response.keyboard,
        )
        return
    if response.result is ActionResult.FAIL:
        await _replace_status(bot, chat_id, status_msg_id, response.text)
        return
    if response.result is ActionResult.CONFIRM:
        tag = uuid.uuid4().hex[:8]
        await state.update_data(
            intake_tag=tag,
            intake_action=action.name,
            intake_payload=response.pending_payload or {},
            intake_args_so_far=args,
        )
        await state.set_state(IntakePending.confirming)
        await _replace_status(
            bot, chat_id, status_msg_id, response.text,
            reply_markup=confirm_card_kb(
                tag=tag,
                editable_fields=response.editable_fields,
            ),
        )
        return
    if response.result is ActionResult.CLARIFY:
        if not response.clarify_options:
            log.warning("intake: CLARIFY without options for %s", action.name)
            await _replace_status(bot, chat_id, status_msg_id, response.text)
            return
        tag = uuid.uuid4().hex[:8]
        rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text=opt.label,
                    callback_data=IntakeCD(
                        action="clarify", tag=tag, index=idx
                    ).pack(),
                )
            ]
            for idx, opt in enumerate(response.clarify_options)
        ]
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=IntakeCD(action="cancel", tag=tag).pack(),
                )
            ]
        )
        await state.update_data(
            intake_tag=tag,
            intake_action=action.name,
            intake_args_so_far=args,
            intake_clarify_payloads=[opt.payload for opt in response.clarify_options],
        )
        await state.set_state(IntakePending.clarifying)
        await _replace_status(
            bot, chat_id, status_msg_id, response.text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )


def _llm_error_text(exc: Exception) -> str:
    """Map LLM SDK exception to user-friendly Russian text."""
    msg = str(exc).lower()
    if "503" in msg or "unavailable" in msg or "overload" in msg or "high demand" in msg:
        return (
            "🤖 Сервис распознавания временно перегружен — "
            "попробуй через 30 секунд или сделай кнопками."
        )
    if "429" in msg or "quota" in msg or "rate limit" in msg.replace("_", " "):
        return (
            "🤖 Дневной лимит распознавания исчерпан — "
            "попробуй завтра или сделай кнопками."
        )
    return "🤖 Не могу разобрать команду — попробуй ещё раз или сделай кнопками."


def _help_text() -> str:
    return (
        "Не понял команду — попробуй переписать или сделай вручную.\n\n"
        "Можешь сказать или написать:\n"
        "• «запиши Иру на завтра в 14:30»\n"
        "• «покажи записи на сегодня»\n"
        "• «перенеси Иру на 16:00»\n"
        "• «отмени запись Иры»\n"
        "• «добавь к записи Иры заметку гель»\n"
        "• «покажи историю Иры»"
    )


# ---------- callbacks: confirm card ------------------------------------------


@router.callback_query(IntakePending.confirming, IntakeCD.filter(F.action == "confirm"))
async def on_confirm(
    callback: CallbackQuery,
    callback_data: IntakeCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    fsm_data = await state.get_data()
    if fsm_data.get("intake_tag") != callback_data.tag:
        await callback.answer("Эта кнопка устарела.", show_alert=True)
        return
    action_name = fsm_data.get("intake_action")
    payload = fsm_data.get("intake_payload") or {}
    registry = _ensure_registry()
    action = registry.get(action_name) if action_name else None
    if action is None:
        await callback.answer("Команда не найдена.", show_alert=True)
        await state.clear()
        return

    factory = cast(async_sessionmaker[Any], data["session_factory"])
    scheduler = data.get("scheduler")
    notify_runner = data.get("notify_runner")
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    # Replace confirm-card with «⏳ Сохраняю…» so user has visual feedback.
    await _edit_status(bot, chat_id, msg_id, "⏳ Сохраняю…")
    await callback.answer()

    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        ctx = ActionContext(
            session=session,
            bot=bot,
            chat_id=chat_id,
            state=state,
            scheduler=scheduler,
            notify_runner=notify_runner,
            tz=tz,
            now_utc=now_utc,
        )
        response = await action.execute(ctx, payload)

    await state.clear()
    await _replace_status(
        bot, chat_id, msg_id, response.text, reply_markup=response.keyboard
    )


@router.callback_query(IntakePending.confirming, IntakeCD.filter(F.action == "cancel"))
async def on_confirm_cancel(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.clear()
    await _replace_status(
        bot, callback.message.chat.id, callback.message.message_id, "❌ Отменено."
    )
    await callback.answer()


@router.callback_query(IntakePending.confirming, IntakeCD.filter(F.action == "edit"))
async def on_edit(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    """Handoff to manual flow — for MVP we drop the pending state and tell
    the user to use the menu. Full FSM-handoff lands in a future polish task.
    """
    if callback.message is None:
        await callback.answer()
        return
    await state.clear()
    await _replace_status(
        bot,
        callback.message.chat.id,
        callback.message.message_id,
        "Открой нужный пункт меню для ручного редактирования (+ Запись / 📋 Записи).",
    )
    await callback.answer()


# ---------- callbacks: clarify -----------------------------------------------


@router.callback_query(IntakePending.clarifying, IntakeCD.filter(F.action == "clarify"))
async def on_clarify(
    callback: CallbackQuery,
    callback_data: IntakeCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    fsm_data = await state.get_data()
    if fsm_data.get("intake_tag") != callback_data.tag:
        await callback.answer("Эта кнопка устарела.", show_alert=True)
        return
    action_name = fsm_data.get("intake_action")
    args = dict(fsm_data.get("intake_args_so_far", {}))
    payloads = fsm_data.get("intake_clarify_payloads") or []
    if callback_data.index >= len(payloads):
        await callback.answer("Эта кнопка устарела.", show_alert=True)
        return

    args.update(payloads[callback_data.index])

    registry = _ensure_registry()
    action = registry.get(action_name) if action_name else None
    if action is None:
        await callback.answer("Команда не найдена.", show_alert=True)
        await state.clear()
        return

    factory = cast(async_sessionmaker[Any], data["session_factory"])
    scheduler = data.get("scheduler")
    notify_runner = data.get("notify_runner")
    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    # Replace clarify-card with «⏳ Обрабатываю…» so user has visual feedback.
    await _edit_status(bot, chat_id, msg_id, "⏳ Обрабатываю команду…")
    await callback.answer()

    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        ctx = ActionContext(
            session=session,
            bot=bot,
            chat_id=chat_id,
            state=state,
            scheduler=scheduler,
            notify_runner=notify_runner,
            tz=tz,
            now_utc=now_utc,
        )
        response = await action.plan(ctx, args)

    await _render(
        bot=bot,
        chat_id=chat_id,
        state=state,
        action=action,
        args=args,
        response=response,
        status_msg_id=msg_id,
    )


@router.callback_query(IntakePending.clarifying, IntakeCD.filter(F.action == "cancel"))
async def on_clarify_cancel(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.clear()
    await _replace_status(
        bot, callback.message.chat.id, callback.message.message_id, "❌ Отменено."
    )
    await callback.answer()
