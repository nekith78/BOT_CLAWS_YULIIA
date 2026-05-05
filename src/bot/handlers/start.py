"""/start command handler — greets the owner and shows the main menu."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.keyboards.main_menu import main_menu_kb

router = Router(name="start")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else "владелец"
    await message.answer(
        text=(
            f"Привет, {name}!\n"
            f"Я твой ассистент для записей.\n"
            f"Жми «+ Запись» чтобы начать, или /help для списка команд."
        ),
        reply_markup=main_menu_kb(),
    )
