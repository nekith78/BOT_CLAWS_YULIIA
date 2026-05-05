"""Display formatter tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.services.formatters import (
    format_appointment_line,
    format_date_ru,
    format_period_header,
    group_by_day,
)
from src.storage.models import Appointment, Client

TZ = ZoneInfo("Asia/Almaty")


def _appt(
    starts_at: datetime,
    *,
    client_name: str = "Олег",
    note: str | None = "маникюр",
) -> tuple[Appointment, Client]:
    client = Client(
        id=1, name=client_name, instagram=None, notes=None, created_at=starts_at
    )
    appt = Appointment(
        id=10,
        client_id=1,
        starts_at=starts_at,
        duration_min=60,
        visit_note=note,
        status="scheduled",
        created_at=starts_at,
    )
    return appt, client


class TestFormatAppointmentLine:
    def test_with_note(self) -> None:
        appt, c = _appt(datetime(2026, 5, 6, 14, 0, tzinfo=TZ))
        assert format_appointment_line(appt, c, tz=TZ) == "14:00 · Олег · маникюр"

    def test_without_note(self) -> None:
        appt, c = _appt(datetime(2026, 5, 6, 14, 0, tzinfo=TZ), note=None)
        assert format_appointment_line(appt, c, tz=TZ) == "14:00 · Олег"

    def test_converts_to_local_tz(self) -> None:
        # appointment в UTC, форматирование в Asia/Almaty (+05:00)
        appt, c = _appt(datetime(2026, 5, 6, 9, 0, tzinfo=ZoneInfo("UTC")))
        assert format_appointment_line(appt, c, tz=TZ).startswith("14:00")

    def test_naive_datetime_treated_as_utc(self) -> None:
        # Foundation хранит starts_at как naive UTC — на показе превращаем в локаль
        appt, c = _appt(datetime(2026, 5, 6, 9, 0))  # naive
        assert format_appointment_line(appt, c, tz=TZ).startswith("14:00")


class TestFormatDateRu:
    def test_basic(self) -> None:
        d = datetime(2026, 5, 6, 0, 0, tzinfo=TZ)  # среда
        assert format_date_ru(d) == "6 мая (ср)"

    def test_january_first(self) -> None:
        d = datetime(2026, 1, 1, 0, 0, tzinfo=TZ)  # четверг
        assert format_date_ru(d) == "1 января (чт)"


class TestGroupByDay:
    def test_groups_by_local_date(self) -> None:
        a1, c = _appt(datetime(2026, 5, 6, 14, 0, tzinfo=TZ))
        a2, _ = _appt(
            datetime(2026, 5, 6, 15, 0, tzinfo=TZ), client_name="Аня", note=None
        )
        a3, _ = _appt(
            datetime(2026, 5, 7, 10, 0, tzinfo=TZ), client_name="Боря", note="педикюр"
        )
        result = group_by_day([(a1, c), (a2, c), (a3, c)], tz=TZ)
        assert list(result.keys()) == [
            datetime(2026, 5, 6, tzinfo=TZ).date(),
            datetime(2026, 5, 7, tzinfo=TZ).date(),
        ]
        assert len(result[datetime(2026, 5, 6, tzinfo=TZ).date()]) == 2
        assert len(result[datetime(2026, 5, 7, tzinfo=TZ).date()]) == 1

    def test_empty_input(self) -> None:
        assert group_by_day([], tz=TZ) == {}


class TestFormatPeriodHeader:
    def test_today(self) -> None:
        assert "Сегодня" in format_period_header(
            "today", anchor=datetime(2026, 5, 6, tzinfo=TZ)
        )

    def test_tomorrow(self) -> None:
        assert "Завтра" in format_period_header(
            "tomorrow", anchor=datetime(2026, 5, 6, tzinfo=TZ)
        )

    def test_week(self) -> None:
        assert "Неделя" in format_period_header(
            "week", anchor=datetime(2026, 5, 6, tzinfo=TZ)
        )

    def test_month(self) -> None:
        header = format_period_header("month", anchor=datetime(2026, 5, 6, tzinfo=TZ))
        assert "Май" in header and "2026" in header

    def test_all(self) -> None:
        assert "Все" in format_period_header(
            "all", anchor=datetime(2026, 5, 6, tzinfo=TZ)
        )

    def test_date(self) -> None:
        # При kind="date" заголовок — это форматированная дата.
        assert "6 мая" in format_period_header(
            "date", anchor=datetime(2026, 5, 6, tzinfo=TZ)
        )
