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
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.callback_data import (
    CalendarCD,
    ClientCD,
    IntakeCD,
    TimeCD,
    TimePartCD,
)
from src.bot.keyboards.calendar import calendar_kb
from src.bot.keyboards.client_picker import client_picker_kb
from src.bot.keyboards.confirm_card import confirm_card_kb
from src.bot.keyboards.edit_field_picker import edit_field_picker_kb
from src.bot.keyboards.time_part_picker import (
    time_hour_picker_kb,
    time_minute_picker_kb,
)
from src.bot.keyboards.time_picker import time_picker_kb
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
    EditableField,
)
from src.services.voice.stt import STTProvider
from src.storage.db import session_scope
from src.storage.repositories.clients import ClientRepository

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


@router.message(
    F.voice,
    ~StateFilter(IntakePending.editing_field_text),
)
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
    & ~F.text.in_(_RESERVED_TEXT_BUTTONS),
    ~StateFilter(IntakePending.editing_field_text),
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
            intake_editable_fields=_serialize_editable_fields(response.editable_fields),
            intake_edit_msg_id=status_msg_id,
        )
        await state.set_state(IntakePending.confirming)
        await _replace_status(
            bot, chat_id, status_msg_id, response.text,
            reply_markup=_confirm_kb_for(action, tag, response.editable_fields),
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


def _confirm_kb_for(
    action: Action, tag: str, editable_fields: list[EditableField] | None
) -> Any:
    """Build the confirm-card keyboard with labels declared by the action.
    Drops the «Изменить» button when the action exposes no editable
    fields (cancel / delete / etc.)."""
    return confirm_card_kb(
        tag=tag,
        confirm_label=getattr(action, "confirm_label", "✅ Сохранить"),
        cancel_label=getattr(action, "cancel_label", "❌ Отменить"),
        show_edit=bool(editable_fields),
    )


def _confirm_kb_from_fsm(
    fsm: dict[str, Any], tag: str
) -> Any:
    """Same as `_confirm_kb_for` but reads the action by name from FSM
    data — used by re-render paths (cancel-edit, back-to-confirm) where
    we don't have the action reference handy."""
    action_name = fsm.get("intake_action")
    registry = _ensure_registry()
    action = registry.get(action_name) if action_name else None
    fields = _restore_editable_fields(fsm)
    if action is None:
        return confirm_card_kb(tag=tag)
    return _confirm_kb_for(action, tag, fields)


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
    callback: CallbackQuery,
    callback_data: IntakeCD,
    state: FSMContext,
    bot: Bot,
    **_: Any,
) -> None:
    """User tapped «✏️ Изменить» — open the field-picker submenu.

    If the action declared no editable fields (e.g. cancel/delete), we
    fall back to an inline hint pointing at the manual menu — there's
    nothing structured to edit per-field.
    """
    if callback.message is None:
        await callback.answer()
        return
    fsm = await state.get_data()
    if fsm.get("intake_tag") != callback_data.tag:
        await callback.answer("Эта кнопка устарела.", show_alert=True)
        return
    fields = _restore_editable_fields(fsm)
    if not fields:
        # No structured edit available — drop the pending state and hint.
        await state.clear()
        await _replace_status(
            bot,
            callback.message.chat.id,
            callback.message.message_id,
            "Это действие нельзя отредактировать по полям. Отмени и переделай командой.",
        )
        await callback.answer()
        return

    await state.set_state(IntakePending.choosing_edit_field)
    await _replace_status(
        bot,
        callback.message.chat.id,
        callback.message.message_id,
        "Что хочешь изменить?",
        reply_markup=edit_field_picker_kb(tag=callback_data.tag, fields=fields),
    )
    await callback.answer()


@router.callback_query(
    IntakePending.choosing_edit_field, IntakeCD.filter(F.action == "back_to_confirm")
)
async def on_back_to_confirm(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any
) -> None:
    """User tapped «← Назад» on the field-picker — re-render the
    confirm-card from current FSM args (no merge applied)."""
    await _replan_after_edit(
        callback=callback, state=state, bot=bot, data=data,
        field_key="", new_args_patch={},
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


# ---------- per-field edit ---------------------------------------------------
#
# When user taps «✏️ Изменить <field>» on the confirm-card, we open the
# right editor (calendar / time-picker / client-picker / text-input) on the
# SAME message. After the user picks/types a new value, we merge it into
# the action's args, re-call `action.plan()` (no LLM hit), and re-render
# the confirm-card with the updated value.
#
# State machine:
#   confirming → (tap edit_field) → editing_field_picker (for date/time/client)
#                                  → editing_field_text   (for note/instagram)
#   any-edit    → (pick / type / cancel) → confirming

# Special «cancel-back» token used as `back_callback_data` in pickers.
# Picker keyboards already accept arbitrary callback_data strings — we
# embed it as `IntakeCD(action="cancel_edit")` so a single handler restores
# the confirm-card from any of the 3 picker editors.


def _editable_field_lookup(
    fields: list[dict[str, Any]] | None, key: str
) -> EditableField | None:
    """FSM-stashed `editable_fields_dump` is a list of dicts (FSM serialises
    dataclasses through redis as plain dicts). Reconstruct the matching
    EditableField, returning None when not found."""
    if not fields:
        return None
    for raw in fields:
        if raw.get("key") == key:
            return EditableField(
                key=raw["key"],
                label=raw["label"],
                editor=raw["editor"],
                prompt_text=raw.get("prompt_text"),
            )
    return None


def _serialize_editable_fields(
    fields: list[EditableField] | None,
) -> list[dict[str, Any]] | None:
    if fields is None:
        return None
    return [
        {
            "key": f.key,
            "label": f.label,
            "editor": f.editor,
            "prompt_text": f.prompt_text,
        }
        for f in fields
    ]


async def _replan_after_edit(
    *,
    callback: CallbackQuery,
    state: FSMContext,
    bot: Bot,
    data: dict[str, Any],
    field_key: str,
    new_args_patch: dict[str, Any],
) -> None:
    """Merge `new_args_patch` into the in-flight action args, re-call
    `action.plan()` and re-render the confirm-card on the same message.
    No LLM call is made — this is purely arg merging + action replay.
    """
    if callback.message is None:
        return
    fsm = await state.get_data()
    tag = fsm.get("intake_tag")
    action_name = fsm.get("intake_action")
    args_so_far = dict(fsm.get("intake_args_so_far") or {})
    payload = dict(fsm.get("intake_payload") or {})

    # Carry resolved IDs forward so plan() doesn't redo lookups.
    if "client_id" in payload and payload["client_id"] is not None:
        args_so_far["client_id"] = payload["client_id"]
    if "appointment_id" in payload:
        args_so_far["appointment_id"] = payload["appointment_id"]

    # Apply the user's edit. The patch already carries field_key+value;
    # for client_picker it also brings `client_name`.
    args_so_far.update(new_args_patch)
    log.info(
        "intake edit: action=%s field=%s patch=%s",
        action_name, field_key, new_args_patch,
    )

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
        response = await action.plan(ctx, args_so_far)

    if response.result is ActionResult.CONFIRM:
        await state.update_data(
            intake_args_so_far=args_so_far,
            intake_payload=response.pending_payload or {},
            intake_editable_fields=_serialize_editable_fields(response.editable_fields),
        )
        await state.set_state(IntakePending.confirming)
        await _replace_status(
            bot, chat_id, msg_id, response.text,
            reply_markup=_confirm_kb_for(action, str(tag or ""), response.editable_fields),
        )
    elif response.result is ActionResult.FAIL:
        # The edit broke something (e.g. past date). Show the error,
        # keep the previous confirm-card payload so user can try again.
        await callback.answer(response.text, show_alert=True)
        await state.set_state(IntakePending.confirming)
        # Re-render existing confirm-card from FSM (text + payload unchanged).
        prev_text = (
            "⚠️ "
            + response.text
            + "\n\nВернись к редактированию — старые поля сохранены."
        )
        await _replace_status(
            bot, chat_id, msg_id, prev_text,
            reply_markup=_confirm_kb_for(action, str(tag or ""), _restore_editable_fields(fsm)),
        )
    else:
        # CLARIFY mid-edit is rare (e.g. resolve_client suddenly returned
        # multi-match). Treat like FAIL — alert + keep the old card.
        await callback.answer(
            "Изменение поля привело к неоднозначности — отмени и попробуй ещё раз.",
            show_alert=True,
        )
        await state.set_state(IntakePending.confirming)


def _restore_editable_fields(fsm_data: dict[str, Any]) -> list[EditableField] | None:
    raw = fsm_data.get("intake_editable_fields")
    if not raw:
        return None
    return [
        EditableField(
            key=item["key"],
            label=item["label"],
            editor=item["editor"],
            prompt_text=item.get("prompt_text"),
        )
        for item in raw
    ]


@router.callback_query(
    IntakePending.choosing_edit_field, IntakeCD.filter(F.action == "edit_field")
)
async def on_edit_field(
    callback: CallbackQuery,
    callback_data: IntakeCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    """User tapped «✏️ Изменить <field>». Open the matching editor on
    the same message and switch to the appropriate edit-state."""
    if callback.message is None:
        await callback.answer()
        return

    fsm = await state.get_data()
    if fsm.get("intake_tag") != callback_data.tag:
        await callback.answer("Эта кнопка устарела.", show_alert=True)
        return

    fields_raw = fsm.get("intake_editable_fields") or []
    field = _editable_field_lookup(fields_raw, callback_data.field)
    if field is None:
        await callback.answer("Это поле уже нельзя править.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    msg_id = callback.message.message_id

    # Stash editing meta so picker callbacks know which field they answer.
    await state.update_data(
        intake_editing_field=callback_data.field,
    )

    if field.editor == "calendar":
        anchor_date = _extract_anchor_date(fsm) or datetime.now(timezone.utc).date()
        cancel_cd = IntakeCD(action="cancel_edit", tag=callback_data.tag).pack()
        await _replace_status(
            bot, chat_id, msg_id,
            f"📅 Выбери новую {field.label.lower()}:",
            reply_markup=calendar_kb(
                anchor=anchor_date,
                back_callback_data=cancel_cd,
            ),
        )
        await state.set_state(IntakePending.editing_field_picker)
    elif field.editor == "time_picker":
        await _replace_status(
            bot, chat_id, msg_id,
            f"🕐 Выбери новое {field.label.lower()}:",
            reply_markup=time_picker_kb(),
        )
        await state.set_state(IntakePending.editing_field_picker)
    elif field.editor == "client_picker":
        factory = cast(async_sessionmaker[Any], data["session_factory"])
        async with session_scope(factory) as session:
            recent = await ClientRepository(session).list_recent(limit=10)
        await _replace_status(
            bot, chat_id, msg_id,
            "👤 Выбери клиента:",
            reply_markup=client_picker_kb(recent=recent),
        )
        await state.set_state(IntakePending.editing_field_picker)
    elif field.editor == "text_input":
        prompt = field.prompt_text or f"Напиши новое значение для {field.label.lower()}:"
        cancel_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ Отмена",
                        callback_data=IntakeCD(
                            action="cancel_edit", tag=callback_data.tag
                        ).pack(),
                    )
                ]
            ]
        )
        await _replace_status(
            bot, chat_id, msg_id, prompt, reply_markup=cancel_kb
        )
        await state.set_state(IntakePending.editing_field_text)

    await callback.answer()


def _extract_anchor_date(fsm: dict[str, Any]) -> Any:
    """Pull the calendar anchor from the action's current args/payload —
    falls back to today when nothing useful is there."""
    from datetime import date

    args = fsm.get("intake_args_so_far") or {}
    for key in ("date", "new_date"):
        val = args.get(key)
        if isinstance(val, str):
            try:
                return date.fromisoformat(val)
            except ValueError:
                continue
    return None


# --- picker pick handlers (state filtered to editing_field_picker) -----


@router.callback_query(IntakePending.editing_field_picker, CalendarCD.filter(F.action == "pick"))
async def on_edit_calendar_pick(
    callback: CallbackQuery,
    callback_data: CalendarCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    fsm = await state.get_data()
    field_key = fsm.get("intake_editing_field")
    if not field_key:
        await callback.answer()
        return
    await _replan_after_edit(
        callback=callback,
        state=state,
        bot=bot,
        data=data,
        field_key=field_key,
        new_args_patch={field_key: callback_data.iso_date},
    )
    await callback.answer()


@router.callback_query(IntakePending.editing_field_picker, CalendarCD.filter(F.action == "nav"))
async def on_edit_calendar_nav(
    callback: CallbackQuery,
    callback_data: CalendarCD,
    state: FSMContext,
    bot: Bot,
    **_: Any,
) -> None:
    """Month nav inside the edit calendar — re-render with the new anchor."""
    if callback.message is None:
        await callback.answer()
        return
    from datetime import date, timedelta

    anchor = date.fromisoformat(callback_data.iso_date)
    delta = -1 if callback_data.nav == "prev" else 32
    new_anchor = (anchor + timedelta(days=delta)).replace(day=1)
    fsm = await state.get_data()
    cancel_cd = IntakeCD(action="cancel_edit", tag=str(fsm.get("intake_tag") or "")).pack()
    await _replace_status(
        bot, callback.message.chat.id, callback.message.message_id,
        "📅 Выбери новую дату:",
        reply_markup=calendar_kb(anchor=new_anchor, back_callback_data=cancel_cd),
    )
    await callback.answer()


@router.callback_query(IntakePending.editing_field_picker, CalendarCD.filter(F.action == "noop"))
async def on_edit_calendar_noop(callback: CallbackQuery, **_: Any) -> None:
    await callback.answer()


@router.callback_query(IntakePending.editing_field_picker, TimeCD.filter())
async def on_edit_time_pick(
    callback: CallbackQuery,
    callback_data: TimeCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    """Time grid pick — either a direct HH:MM or 'custom' which opens the
    hour-then-minute fallback."""
    if callback.message is None:
        await callback.answer()
        return
    fsm = await state.get_data()
    field_key = fsm.get("intake_editing_field")
    if not field_key:
        await callback.answer()
        return
    if callback_data.hhmm == "custom":
        await _replace_status(
            bot, callback.message.chat.id, callback.message.message_id,
            "Выбери час:",
            reply_markup=time_hour_picker_kb(),
        )
        await callback.answer()
        return
    await _replan_after_edit(
        callback=callback,
        state=state,
        bot=bot,
        data=data,
        field_key=field_key,
        new_args_patch={field_key: callback_data.hhmm},
    )
    await callback.answer()


@router.callback_query(IntakePending.editing_field_picker, TimePartCD.filter())
async def on_edit_time_part(
    callback: CallbackQuery,
    callback_data: TimePartCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    """Hybrid hour→minute picker for «другое время»."""
    if callback.message is None:
        await callback.answer()
        return
    if callback_data.action == "hour":
        await _replace_status(
            bot, callback.message.chat.id, callback.message.message_id,
            f"Минуты для {callback_data.hh:02d}:__",
            reply_markup=time_minute_picker_kb(hh=callback_data.hh),
        )
    elif callback_data.action == "minute":
        fsm = await state.get_data()
        field_key = fsm.get("intake_editing_field")
        if not field_key:
            await callback.answer()
            return
        hhmm = f"{callback_data.hh:02d}:{callback_data.mm:02d}"
        await _replan_after_edit(
            callback=callback, state=state, bot=bot, data=data,
            field_key=field_key, new_args_patch={field_key: hhmm},
        )
    elif callback_data.action == "back_to_hours":
        await _replace_status(
            bot, callback.message.chat.id, callback.message.message_id,
            "Выбери час:", reply_markup=time_hour_picker_kb(),
        )
    elif callback_data.action == "back_to_grid":
        await _replace_status(
            bot, callback.message.chat.id, callback.message.message_id,
            "Выбери время:", reply_markup=time_picker_kb(),
        )
    await callback.answer()


@router.callback_query(IntakePending.editing_field_picker, ClientCD.filter(F.action == "pick"))
async def on_edit_client_pick(
    callback: CallbackQuery,
    callback_data: ClientCD,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    fsm = await state.get_data()
    field_key = fsm.get("intake_editing_field")
    if not field_key:
        await callback.answer()
        return
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    async with session_scope(factory) as session:
        client = await ClientRepository(session).get(callback_data.client_id)
    if client is None:
        await callback.answer("Клиент не найден.", show_alert=True)
        return
    # client_picker fields update both client_id and client_name in args.
    await _replan_after_edit(
        callback=callback, state=state, bot=bot, data=data,
        field_key=field_key,
        new_args_patch={field_key: client.name, "client_id": client.id},
    )
    await callback.answer()


# --- text-input handlers (state filtered to editing_field_text) --------


@router.message(IntakePending.editing_field_text, F.text)
async def on_edit_text_input(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    """Bot is waiting for a text/voice value for a text_input field.
    Plain text → use as value directly."""
    if message.text is None:
        return
    text = message.text.strip()
    if not text:
        return
    await _commit_text_field_edit(
        message=message, state=state, bot=bot, data=data, value=text
    )


@router.message(IntakePending.editing_field_text, F.voice)
async def on_edit_voice_input(
    message: Message, state: FSMContext, bot: Bot, **data: Any
) -> None:
    """Voice during text-edit mode: transcribe via STT and use the
    transcript as the field value (same path as text input)."""
    if message.voice is None:
        return
    settings = data.get("settings")
    stt: STTProvider | None = data.get("stt")
    if stt is None or settings is None:
        return
    if (message.voice.duration or 0) > settings.voice_max_duration_sec:
        await bot.send_message(
            message.chat.id,
            f"Слишком длинное сообщение — до {settings.voice_max_duration_sec} сек.",
        )
        return
    file = await bot.get_file(message.voice.file_id)
    if file.file_path is None:
        return
    buf = io.BytesIO()
    await bot.download_file(file.file_path, buf)
    transcript = (await stt.transcribe(buf.getvalue(), mime="audio/ogg")).strip()
    if not transcript:
        await bot.send_message(message.chat.id, "Не услышал ничего, попробуй ещё раз.")
        return
    await _commit_text_field_edit(
        message=message, state=state, bot=bot, data=data, value=transcript
    )


async def _commit_text_field_edit(
    *,
    message: Message,
    state: FSMContext,
    bot: Bot,
    data: dict[str, Any],
    value: str,
) -> None:
    """Shared text-input merge path. Constructs a fake CallbackQuery-like
    target to reuse `_replan_after_edit` — simpler than duplicating the
    helper."""
    fsm = await state.get_data()
    field_key = fsm.get("intake_editing_field")
    confirm_msg_id = fsm.get("intake_edit_msg_id") or fsm.get("intake_edit_origin_msg_id")
    if not field_key:
        return

    # We need the original confirm-card message id to edit. Stored at
    # the start of the edit flow as `intake_edit_msg_id`. Fall back: send
    # a new message if missing.
    chat_id = message.chat.id

    # Build a callback-like context for the helper. Simpler: inline the
    # replan logic since `_replan_after_edit` expects a CallbackQuery.
    args_so_far = dict(fsm.get("intake_args_so_far") or {})
    payload = dict(fsm.get("intake_payload") or {})
    if "client_id" in payload and payload["client_id"] is not None:
        args_so_far["client_id"] = payload["client_id"]
    if "appointment_id" in payload:
        args_so_far["appointment_id"] = payload["appointment_id"]
    args_so_far[field_key] = value
    log.info("intake edit (text): field=%s value=%r", field_key, value)

    registry = _ensure_registry()
    action_name = fsm.get("intake_action")
    action = registry.get(action_name) if action_name else None
    if action is None:
        await state.clear()
        await bot.send_message(chat_id, "Команда не найдена.")
        return

    factory = cast(async_sessionmaker[Any], data["session_factory"])
    scheduler = data.get("scheduler")
    notify_runner = data.get("notify_runner")
    async with session_scope(factory) as session:
        tz = await settings_service.get_timezone(session)
        now_utc = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        ctx = ActionContext(
            session=session, bot=bot, chat_id=chat_id, state=state,
            scheduler=scheduler, notify_runner=notify_runner,
            tz=tz, now_utc=now_utc,
        )
        response = await action.plan(ctx, args_so_far)

    tag = str(fsm.get("intake_tag") or "")
    if response.result is ActionResult.CONFIRM:
        await state.update_data(
            intake_args_so_far=args_so_far,
            intake_payload=response.pending_payload or {},
            intake_editable_fields=_serialize_editable_fields(response.editable_fields),
        )
        await state.set_state(IntakePending.confirming)
        kb = _confirm_kb_for(action, tag, response.editable_fields)
        if confirm_msg_id:
            await _replace_status(
                bot, chat_id, int(confirm_msg_id), response.text, reply_markup=kb,
            )
        else:
            sent = await bot.send_message(chat_id, response.text, reply_markup=kb)
            await state.update_data(intake_edit_msg_id=sent.message_id)
    else:
        await bot.send_message(chat_id, f"⚠️ {response.text}")
        await state.set_state(IntakePending.confirming)


# --- cancel-edit (works for both picker and text edit states) ---------


@router.callback_query(
    IntakePending.editing_field_picker, IntakeCD.filter(F.action == "cancel_edit")
)
@router.callback_query(
    IntakePending.editing_field_text, IntakeCD.filter(F.action == "cancel_edit")
)
async def on_cancel_edit(
    callback: CallbackQuery, state: FSMContext, bot: Bot, **data: Any
) -> None:
    """User pressed «❌ Отмена» inside an editor sub-flow — restore the
    confirm-card with original args, no merge applied. We just re-call
    `_replan_after_edit` with an empty patch — it'll re-render the same
    card from current FSM args."""
    await _replan_after_edit(
        callback=callback, state=state, bot=bot, data=data,
        field_key="", new_args_patch={},
    )
    await callback.answer()
