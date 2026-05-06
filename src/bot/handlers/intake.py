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
from datetime import datetime, timezone
from typing import Any, cast

from aiogram import Bot, F, Router
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

    duration = message.voice.duration or 0
    if duration > settings.voice_max_duration_sec:
        await bot.send_message(
            chat_id=message.chat.id,
            text=f"Слишком длинное сообщение — до {settings.voice_max_duration_sec} сек.",
        )
        return

    # Download voice as bytes.
    file = await bot.get_file(message.voice.file_id)
    if file.file_path is None:
        await bot.send_message(message.chat.id, "Не удалось скачать голосовое.")
        return
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    audio = buf.getvalue()

    transcript = await stt.transcribe(audio, mime="audio/ogg")
    if not transcript.strip():
        await bot.send_message(
            message.chat.id, "Не услышал ничего. Попробуй ещё раз."
        )
        return

    log.info("intake voice → transcript: %r", transcript)
    await _dispatch(message=message, state=state, bot=bot, transcript=transcript, data=data)


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
    await _dispatch(message=message, state=state, bot=bot, transcript=text, data=data)


# ---------- common dispatch --------------------------------------------------


async def _dispatch(
    *,
    message: Message,
    state: FSMContext,
    bot: Bot,
    transcript: str,
    data: dict[str, Any],
) -> None:
    chat_id = message.chat.id

    # If user is mid-wizard, cancel it gracefully — voice always interrupts.
    cur_state = await state.get_state()
    if cur_state is not None:
        await ui_cancel(bot, chat_id=chat_id, state=state)

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
        prompt = build_system_prompt(now_local=now_local, tz=settings.owner_tz)

        try:
            parsed = await llm.parse_intent(
                text=transcript,
                tools=tools,
                system=prompt,
                now_local=now_local,
            )
        except Exception:
            log.exception("intake: LLM parse failed")
            await bot.send_message(
                chat_id, "Не могу разобрать команду — попробуй кнопками."
            )
            return

        if parsed.tool_name is None:
            await bot.send_message(chat_id, _help_text())
            return

        action = registry.get(parsed.tool_name)
        if action is None:
            log.warning("intake: LLM picked unknown tool %s", parsed.tool_name)
            await bot.send_message(chat_id, _help_text())
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

    # Render outside the session — render needs no DB.
    await _render(
        bot=bot,
        chat_id=chat_id,
        state=state,
        action=action,
        args=parsed.args,
        response=response,
    )


async def _render(
    *,
    bot: Bot,
    chat_id: int,
    state: FSMContext,
    action: Action,
    args: dict[str, Any],
    response: ActionResponse,
) -> None:
    if response.result is ActionResult.EXECUTED:
        await bot.send_message(chat_id, response.text, reply_markup=response.keyboard)
        return
    if response.result is ActionResult.FAIL:
        await bot.send_message(chat_id, response.text)
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
        await bot.send_message(
            chat_id, response.text, reply_markup=confirm_card_kb(tag=tag)
        )
        return
    if response.result is ActionResult.CLARIFY:
        if not response.clarify_options:
            log.warning("intake: CLARIFY without options for %s", action.name)
            await bot.send_message(chat_id, response.text)
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
        await bot.send_message(
            chat_id, response.text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )


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
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("intake: edit_reply_markup failed: %s", exc)
    await bot.send_message(chat_id, response.text, reply_markup=response.keyboard)
    await callback.answer()


@router.callback_query(IntakePending.confirming, IntakeCD.filter(F.action == "cancel"))
async def on_confirm_cancel(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("intake: edit failed: %s", exc)
    await bot.send_message(callback.message.chat.id, "❌ Отменено.")
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
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("intake: edit failed: %s", exc)
    await bot.send_message(
        callback.message.chat.id,
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

    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("intake: edit failed: %s", exc)

    await _render(
        bot=bot,
        chat_id=chat_id,
        state=state,
        action=action,
        args=args,
        response=response,
    )
    await callback.answer()


@router.callback_query(IntakePending.clarifying, IntakeCD.filter(F.action == "cancel"))
async def on_clarify_cancel(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **_: Any
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await state.clear()
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception as exc:
            log.debug("intake: edit failed: %s", exc)
    await bot.send_message(callback.message.chat.id, "❌ Отменено.")
    await callback.answer()
