"""Keyboard layout tests."""

from __future__ import annotations

from datetime import date

from aiogram.types import ReplyKeyboardMarkup

from src.bot.keyboards.appointment_card import appointment_card_kb
from src.bot.keyboards.calendar import calendar_kb
from src.bot.keyboards.client_picker import client_picker_kb
from src.bot.keyboards.confirm import confirm_kb
from src.bot.keyboards.date_shortcut import date_shortcut_kb
from src.bot.keyboards.main_menu import main_menu_kb
from src.bot.keyboards.period_picker import period_picker_kb
from src.bot.keyboards.time_picker import time_picker_kb
from src.storage.models import Client


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


class TestTimePicker:
    def test_grid_includes_business_hours(self) -> None:
        kb = time_picker_kb()
        all_text = {b.text for row in kb.inline_keyboard for b in row}
        assert {"09:00", "12:00", "20:00"}.issubset(all_text)
        assert "Другое время" in all_text

    def test_grid_30_minute_step(self) -> None:
        kb = time_picker_kb()
        all_text = {b.text for row in kb.inline_keyboard for b in row}
        # Half-hour slots from 09:00 to 20:30 inclusive = 24 cells
        slot_count = sum(1 for t in all_text if ":" in t and len(t) == 5)
        assert slot_count == 24


class TestPeriodPicker:
    def test_lists_scope(self) -> None:
        kb = period_picker_kb(scope="lists")
        texts = {b.text for row in kb.inline_keyboard for b in row}
        assert {"Сегодня", "Неделя", "Месяц", "Все"}.issubset(texts)

    def test_client_scope_carries_id(self) -> None:
        kb = period_picker_kb(scope="client", scope_id=42)
        for row in kb.inline_keyboard:
            for b in row:
                if b.callback_data and b.callback_data.startswith("period|"):
                    parts = b.callback_data.split("|")
                    # PeriodCD packs as "period|v|kind|scope|scope_id"
                    assert parts[-1] == "42"


class TestClientPicker:
    def test_lists_recent_with_search_and_new(self) -> None:
        clients = [
            Client(id=1, name="Олег", instagram=None, notes=None, created_at=None),
            Client(id=2, name="Аня", instagram=None, notes=None, created_at=None),
        ]
        kb = client_picker_kb(recent=clients)
        texts = [b.text for row in kb.inline_keyboard for b in row]
        assert "Олег" in texts and "Аня" in texts
        assert "🔍 Поиск" in texts and "➕ Новый клиент" in texts


class TestConfirmKb:
    def test_three_buttons(self) -> None:
        kb = confirm_kb()
        texts = [b.text for row in kb.inline_keyboard for b in row]
        assert "✅ Сохранить" in texts
        assert "✏️ Поправить" in texts
        assert "❌ Отмена" in texts


class TestAppointmentCardKb:
    def test_full_actions(self) -> None:
        kb = appointment_card_kb(appointment_id=10)
        texts = [b.text for row in kb.inline_keyboard for b in row]
        assert {"Перенести", "Заметка", "Отменить", "Закрыть"}.issubset(set(texts))

    def test_callback_data_carries_id(self) -> None:
        kb = appointment_card_kb(appointment_id=42)
        for row in kb.inline_keyboard:
            for b in row:
                assert b.callback_data is not None
                assert b.callback_data.startswith("appt|")
                assert b.callback_data.endswith("|42")


class TestDateShortcutKb:
    def test_all_buttons_present(self) -> None:
        kb = date_shortcut_kb()
        texts = {b.text for row in kb.inline_keyboard for b in row}
        assert {"Сегодня", "Завтра", "Послезавтра", "📅 Календарь", "⌨️ Текстом"} == texts
