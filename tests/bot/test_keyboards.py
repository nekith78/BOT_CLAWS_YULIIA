"""Keyboard layout tests."""

from __future__ import annotations

from datetime import date

from aiogram.types import ReplyKeyboardMarkup

from src.bot.keyboards.calendar import calendar_kb
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


class TestCalendarKb:
    def test_renders_for_a_month(self) -> None:
        kb = calendar_kb(anchor=date(2026, 5, 1))
        # 1 title + 1 weekday row + ≥4 week rows + 1 nav row
        assert len(kb.inline_keyboard) >= 7
        all_buttons = [b for row in kb.inline_keyboard for b in row]
        texts = {b.text for b in all_buttons}
        # May 2026 has all days 1..31
        assert "1" in texts and "31" in texts

    def test_title_contains_month_name(self) -> None:
        kb = calendar_kb(anchor=date(2026, 5, 1))
        assert "Май" in kb.inline_keyboard[0][0].text
        assert "2026" in kb.inline_keyboard[0][0].text

    def test_nav_buttons_present(self) -> None:
        kb = calendar_kb(anchor=date(2026, 5, 1))
        last_row = kb.inline_keyboard[-1]
        texts = [b.text for b in last_row]
        assert "«" in texts and "»" in texts

    def test_weekday_header_in_russian(self) -> None:
        kb = calendar_kb(anchor=date(2026, 5, 1))
        weekday_row = kb.inline_keyboard[1]
        assert [b.text for b in weekday_row] == ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

    def test_pick_callback_carries_iso_date(self) -> None:
        kb = calendar_kb(anchor=date(2026, 5, 1))
        # Find button with text "15" — it should carry callback_data for 2026-05-15
        for row in kb.inline_keyboard:
            for b in row:
                if b.text == "15":
                    assert b.callback_data is not None
                    assert "2026-05-15" in b.callback_data
                    return
        raise AssertionError("Did not find button '15'")
