"""Tests for appointment card view + note + cancel + move."""

from __future__ import annotations

from datetime import datetime, time, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.callback_data import ApptCD
from src.bot.handlers.appointment_card import (
    on_cancel_confirmed,
    on_cancel_start,
    on_note_start,
    on_note_text,
    on_view,
)
from src.bot.states import EditAppointment
from src.services import settings_service
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository

TZ = ZoneInfo("Asia/Almaty")


@pytest_asyncio.fixture
async def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=100, user_id=100)
    return FSMContext(storage=storage, key=key)


@pytest_asyncio.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    b.edit_message_text = AsyncMock()
    return b


@pytest_asyncio.fixture
async def session_factory(engine):  # type: ignore[no-untyped-def]
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _cb() -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(chat=MagicMock(id=100))
    cb.answer = AsyncMock()
    return cb


def _utc_naive(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


async def _seeded_appt(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    note: str | None = "маникюр",
) -> int:
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.flush()
        appt = await AppointmentRepository(session).create(
            client_id=client.id,
            starts_at=_utc_naive(datetime(2026, 5, 6, 14, 0, tzinfo=TZ)),
            duration_min=60,
            visit_note=note,
        )
        await session.commit()
        return appt.id


async def test_view_shows_card_with_actions(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    appt_id = await _seeded_appt(session_factory)
    cd = ApptCD(action="view", appointment_id=appt_id)
    await on_view(_cb(), callback_data=cd, state=state, bot=bot, session_factory=session_factory)

    text = bot.send_message.await_args.kwargs["text"]
    assert "Олег" in text
    assert "14:00" in text
    assert "Запланирована" in text
    kb = bot.send_message.await_args.kwargs["reply_markup"]
    btn_texts = [b.text for row in kb.inline_keyboard for b in row]
    assert {"Перенести", "Заметка", "Отменить", "Закрыть"}.issubset(set(btn_texts))


async def test_note_edit_updates_visit_note(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    appt_id = await _seeded_appt(session_factory)
    cd = ApptCD(action="note", appointment_id=appt_id)
    await on_note_start(
        _cb(), callback_data=cd, state=state, bot=bot, session_factory=session_factory
    )
    assert await state.get_state() == EditAppointment.entering_note.state

    msg = MagicMock(spec=Message)
    msg.chat = MagicMock(id=100)
    msg.text = "новая заметка"
    await on_note_text(msg, state=state, bot=bot, session_factory=session_factory)

    async with session_factory() as session:
        appt = await AppointmentRepository(session).get(appt_id)
    assert appt is not None
    assert appt.visit_note == "новая заметка"
    assert await state.get_state() is None


async def test_cancel_confirm_marks_status_cancelled(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    appt_id = await _seeded_appt(session_factory)

    cd = ApptCD(action="cancel", appointment_id=appt_id)
    await on_cancel_start(
        _cb(), callback_data=cd, state=state, bot=bot, session_factory=session_factory
    )
    assert await state.get_state() == EditAppointment.choosing_new_date.state
    data = await state.get_data()
    assert data.get("cancel_confirm") is True
    assert data.get("cancel_appointment_id") == appt_id

    await on_cancel_confirmed(_cb(), state=state, bot=bot, session_factory=session_factory)
    async with session_factory() as session:
        appt = await AppointmentRepository(session).get(appt_id)
    assert appt is not None
    assert appt.status == "cancelled"
    assert await state.get_state() is None


# Used to silence unused-import warnings for `time`.
_ = time
