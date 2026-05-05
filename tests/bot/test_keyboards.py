"""Keyboard layout tests."""

from __future__ import annotations

from aiogram.types import ReplyKeyboardMarkup

from src.bot.keyboards.main_menu import main_menu_kb


def test_main_menu_has_required_buttons() -> None:
    kb = main_menu_kb()
    assert isinstance(kb, ReplyKeyboardMarkup)

    labels = {btn.text for row in kb.keyboard for btn in row}
    assert "+ Запись" in labels
    assert "📅 Сегодня" in labels
    assert "📆 Завтра" in labels
    assert "👥 Клиенты" in labels
    assert "⚙️ Настройки" in labels
