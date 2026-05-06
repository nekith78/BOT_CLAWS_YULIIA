"""Tests for CallbackData factories — round-trip serialization."""
from __future__ import annotations

import pytest

from src.bot.callback_data import (
    ApptCD,
    CalendarCD,
    ClientCD,
    DateShortcutCD,
    PeriodCD,
    TimeCD,
    WizardCD,
)


class TestApptCD:
    def test_round_trip_view(self) -> None:
        cd = ApptCD(action="view", appointment_id=42)
        packed = cd.pack()
        unpacked = ApptCD.unpack(packed)
        assert unpacked == cd

    def test_v_defaults_to_1(self) -> None:
        assert ApptCD(action="view", appointment_id=1).v == 1


class TestClientCD:
    @pytest.mark.parametrize("action", ["pick", "view", "edit", "history", "new"])
    def test_round_trip(self, action: str) -> None:
        cd = ClientCD(action=action, client_id=7)  # type: ignore[arg-type]
        assert ClientCD.unpack(cd.pack()) == cd


class TestCalendarCD:
    def test_pick_carries_iso_date(self) -> None:
        cd = CalendarCD(action="pick", iso_date="2026-05-06")
        assert CalendarCD.unpack(cd.pack()).iso_date == "2026-05-06"

    def test_nav_carries_direction(self) -> None:
        cd = CalendarCD(action="nav", nav="next", iso_date="2026-05-01")
        assert CalendarCD.unpack(cd.pack()).nav == "next"


class TestTimeCD:
    def test_round_trip_hhmm(self) -> None:
        cd = TimeCD(hhmm="14:30")
        assert TimeCD.unpack(cd.pack()).hhmm == "14:30"

    def test_custom_marker(self) -> None:
        cd = TimeCD(hhmm="custom")
        assert TimeCD.unpack(cd.pack()).hhmm == "custom"


class TestPeriodCD:
    @pytest.mark.parametrize("kind", ["today", "week", "month", "all", "date"])
    def test_round_trip(self, kind: str) -> None:
        cd = PeriodCD(kind=kind, scope="client", scope_id=3)  # type: ignore[arg-type]
        assert PeriodCD.unpack(cd.pack()) == cd


class TestWizardCD:
    def test_action_only(self) -> None:
        cd = WizardCD(action="cancel")
        assert WizardCD.unpack(cd.pack()).action == "cancel"


class TestDateShortcutCD:
    @pytest.mark.parametrize(
        "action", ["today", "tomorrow", "day_after", "open_calendar"]
    )
    def test_round_trip(self, action: str) -> None:
        cd = DateShortcutCD(action=action)  # type: ignore[arg-type]
        assert DateShortcutCD.unpack(cd.pack()) == cd
