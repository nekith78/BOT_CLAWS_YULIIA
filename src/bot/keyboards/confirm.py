"""Confirm card actions: ✅ Сохранить / ✏️ Поправить / ❌ Отмена."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.callback_data import WizardCD


def confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сохранить",
                    callback_data=WizardCD(action="save").pack(),
                ),
                InlineKeyboardButton(
                    text="✏️ Поправить",
                    callback_data=WizardCD(action="edit").pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=WizardCD(action="cancel").pack(),
                ),
            ]
        ]
    )
