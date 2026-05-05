"""Smoke tests for AddAppointment FSM flow.

Полный happy path и conflict-check проверяются вручную через Docker
(см. Task 16 manual checklist). Здесь — узкие unit-проверки на:
- entry handler: показывает client picker и устанавливает state.
- save handler: создаёт Appointment с правильным временем (UTC из локали).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.bot.handlers.add_appointment import entry, on_force_save, on_save, router
from src.bot.states import AddAppointment
from src.services import settings_service
from src.storage.repositories.appointments import AppointmentRepository
from src.storage.repositories.clients import ClientRepository


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


def test_router_has_handlers() -> None:
    """Smoke: router was assembled, handlers registered."""
    # Sanity: нет ничего страннее, чем «handler-файл импортируется, но handler'ов нет».
    assert router.name == "add_appointment"
    # router.observers — внутренняя структура aiogram, проверяем что хоть что-то
    # зарегистрировано на message и callback_query.
    assert router.message.handlers, "no message handlers"
    assert router.callback_query.handlers, "no callback_query handlers"


async def test_entry_lists_clients_and_sets_state(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # У нас в БД пусто — entry должен показать "У тебя ещё нет клиентов..."
    message = MagicMock(spec=Message)
    message.chat = MagicMock(id=100)

    await entry(message, state=state, bot=bot, session_factory=session_factory)

    bot.send_message.assert_awaited_once()
    assert "ещё нет клиентов" in bot.send_message.await_args.kwargs["text"]
    assert await state.get_state() == AddAppointment.choosing_client.state


async def test_on_save_creates_appointment_in_utc(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Подготовка: клиент в БД, дефолтные настройки (Asia/Almaty).
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.commit()
        client_id = client.id

    await state.set_state(AddAppointment.confirming)
    await state.update_data(
        client_id=client_id,
        picked_date="2026-05-06",
        picked_time="14:00",
        visit_note="маникюр",
        flow_message_id=555,
    )

    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(chat=MagicMock(id=100))
    cb.answer = AsyncMock()

    await on_save(cb, state=state, bot=bot, session_factory=session_factory)

    # Запись должна сохраниться в UTC (Asia/Almaty 14:00 = 09:00 UTC).
    async with session_factory() as session:
        appts = await AppointmentRepository(session).list_in_range(
            start=datetime(2026, 5, 6, 0, 0),
            end=datetime(2026, 5, 7, 0, 0),
        )
    assert len(appts) == 1
    assert appts[0].client_id == client_id
    assert appts[0].visit_note == "маникюр"
    expected_utc = (
        datetime(2026, 5, 6, 14, 0, tzinfo=ZoneInfo("Asia/Almaty"))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    assert appts[0].starts_at == expected_utc
    assert await state.get_state() is None  # finalize cleared state


async def test_on_save_with_overlap_routes_to_conflict_state(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Готовим клиента + существующую запись на 14:00 локали (= 09:00 UTC).
    expected_utc = (
        datetime(2026, 5, 6, 14, 0, tzinfo=ZoneInfo("Asia/Almaty"))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.flush()
        await AppointmentRepository(session).create(
            client_id=client.id, starts_at=expected_utc, duration_min=60
        )
        await session.commit()
        client_id = client.id

    await state.set_state(AddAppointment.confirming)
    await state.update_data(
        client_id=client_id,
        picked_date="2026-05-06",
        picked_time="14:30",  # пересекается с 14:00..15:00
        flow_message_id=555,
    )

    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(chat=MagicMock(id=100))
    cb.answer = AsyncMock()
    await on_save(cb, state=state, bot=bot, session_factory=session_factory)

    assert await state.get_state() == AddAppointment.resolving_conflict.state
    edit_args = bot.edit_message_text.await_args.kwargs
    assert "уже есть записи" in edit_args["text"]
    assert "Олег" in edit_args["text"]

    # Counts должны быть прежним: новой записи ещё не появилось.
    async with session_factory() as session:
        appts = await AppointmentRepository(session).list_in_range(
            start=datetime(2026, 5, 6, 0, 0),
            end=datetime(2026, 5, 7, 0, 0),
        )
    assert len(appts) == 1


async def test_on_force_save_writes_second_appointment(
    state: FSMContext,
    bot: MagicMock,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    expected_utc = (
        datetime(2026, 5, 6, 14, 0, tzinfo=ZoneInfo("Asia/Almaty"))
        .astimezone(timezone.utc)
        .replace(tzinfo=None)
    )
    async with session_factory() as session:
        await settings_service.seed_defaults(session)
        client = await ClientRepository(session).create(name="Олег")
        await session.flush()
        await AppointmentRepository(session).create(
            client_id=client.id, starts_at=expected_utc, duration_min=60
        )
        await session.commit()
        client_id = client.id

    await state.set_state(AddAppointment.resolving_conflict)
    await state.update_data(
        client_id=client_id,
        picked_date="2026-05-06",
        picked_time="14:30",
        flow_message_id=555,
    )

    cb = MagicMock(spec=CallbackQuery)
    cb.message = MagicMock(chat=MagicMock(id=100))
    cb.answer = AsyncMock()
    await on_force_save(cb, state=state, bot=bot, session_factory=session_factory)

    async with session_factory() as session:
        appts = await AppointmentRepository(session).list_in_range(
            start=datetime(2026, 5, 6, 0, 0),
            end=datetime(2026, 5, 7, 0, 0),
        )
    assert len(appts) == 2
    assert await state.get_state() is None


@pytest_asyncio.fixture
async def session_factory(engine):  # type: ignore[no-untyped-def]
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
