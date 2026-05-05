"""/add YYYY-MM-DD HH:MM Имя [@instagram] [заметка] — fast-path text command.

Парсит строку, находит/создаёт клиента, предзаполняет AddAppointment-state и
переводит в `confirming` — оттуда уже работает on_save из add_appointment.py
со всеми проверками конфликта.
"""

from __future__ import annotations

from typing import Any, cast

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.bot.keyboards.confirm import confirm_kb
from src.bot.states import AddAppointment
from src.bot.ui import advance
from src.services.formatters import format_date_ru
from src.services.parser.text_parser import ParseError, parse_add_command
from src.storage.db import session_scope
from src.storage.repositories.clients import ClientRepository

router = Router(name="text_add")

_USAGE = (
    "Не понял. Формат:\n"
    "<code>/add YYYY-MM-DD HH:MM Имя [@инста] [заметка]</code>\n"
    "Например: <code>/add 2026-05-06 14:30 Олег @oleg маникюр</code>"
)


@router.message(Command("add"))
async def handle_add(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    bot: Bot,
    **data: Any,
) -> None:
    factory = cast(async_sessionmaker[Any], data["session_factory"])
    chat_id = message.chat.id

    if not command.args:
        await bot.send_message(chat_id=chat_id, text=_USAGE)
        return
    try:
        parsed = parse_add_command(command.args)
    except ParseError:
        await bot.send_message(chat_id=chat_id, text=_USAGE)
        return

    async with session_scope(factory) as session:
        repo = ClientRepository(session)
        # Точное совпадение по имени, case-insensitive.
        matches = [
            c for c in await repo.search_by_name(parsed.client_name)
            if c.name.lower() == parsed.client_name.lower()
        ]
        if matches:
            client = matches[0]
        else:
            client = await repo.create(
                name=parsed.client_name, instagram=parsed.instagram
            )
            await session.flush()
        client_id = client.id
        client_name = client.name
        client_insta = client.instagram

    await state.clear()
    await state.update_data(
        client_id=client_id,
        picked_date=parsed.starts_at.date().isoformat(),
        picked_time=parsed.starts_at.strftime("%H:%M"),
        visit_note=parsed.visit_note,
    )

    insta = f"📷 {client_insta}\n" if client_insta else ""
    note_line = f"📝 {parsed.visit_note}\n" if parsed.visit_note else ""
    text = (
        "Записываю:\n"
        f"👤 {client_name}\n"
        f"📅 {format_date_ru(parsed.starts_at)}, {parsed.starts_at.strftime('%H:%M')}\n"
        f"{insta}{note_line}".rstrip()
    )
    await advance(
        bot, chat_id=chat_id, state=state, text=text, reply_markup=confirm_kb()
    )
    await state.set_state(AddAppointment.confirming)
