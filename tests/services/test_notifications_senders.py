"""Format-only tests for notification senders."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.services.notifications.senders import (
    format_eve_digest,
    format_offset_ping,
)
from src.storage.models import Appointment, Client

TZ = ZoneInfo("Asia/Almaty")


def _utc_naive(local: datetime) -> datetime:
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _appt(local_dt: datetime, *, note: str | None = None) -> Appointment:
    return Appointment(
        id=1, client_id=1, starts_at=_utc_naive(local_dt), duration_min=60,
        visit_note=note, status="scheduled", created_at=_utc_naive(local_dt),
    )


def _client(name: str = "Олег") -> Client:
    return Client(id=1, name=name, instagram=None, notes=None, created_at=None)


class TestEveDigest:
    def test_empty(self) -> None:
        assert "записей нет" in format_eve_digest([], tz=TZ)

    def test_one_appointment(self) -> None:
        a = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ), note="маникюр")
        c = _client()
        text = format_eve_digest([(a, c)], tz=TZ)
        assert "Завтра 1 запись:" in text
        assert "14:00 · Олег · маникюр" in text

    def test_three_appointments_sorted_by_time(self) -> None:
        a1 = _appt(datetime(2026, 5, 7, 16, 0, tzinfo=TZ), note="мани")
        a2 = _appt(datetime(2026, 5, 7, 11, 0, tzinfo=TZ), note="педи")
        a3 = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ))
        c = _client("Аня")
        text = format_eve_digest([(a1, c), (a2, c), (a3, c)], tz=TZ)
        # 1 → "запись:", 2-4 → "записи:", 5+ → "записей:"
        assert "Завтра 3 записи:" in text
        # Lines must be sorted by time.
        body = text.split("\n", 1)[1]
        assert body.index("11:00") < body.index("14:00") < body.index("16:00")

    def test_five_uses_genitive_plural(self) -> None:
        c = _client()
        appts = [
            (_appt(datetime(2026, 5, 7, 9 + i, 0, tzinfo=TZ)), c) for i in range(5)
        ]
        text = format_eve_digest(appts, tz=TZ)
        assert "Завтра 5 записей:" in text

    def test_late_prefix(self) -> None:
        a = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ))
        c = _client()
        text = format_eve_digest([(a, c)], tz=TZ, late=True)
        assert text.startswith("⏰ (с задержкой) ")

    def test_html_escape_on_name_and_note(self) -> None:
        a = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ), note="<b>bold</b>")
        c = _client("Иван<3")
        text = format_eve_digest([(a, c)], tz=TZ)
        assert "&lt;b&gt;" in text
        assert "Иван&lt;3" in text


class TestOffsetPing:
    def test_basic(self) -> None:
        a = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ), note="маникюр")
        c = _client()
        text = format_offset_ping(a, c, tz=TZ)
        assert text == "⏰ Через час: 14:00 · Олег · маникюр"

    def test_no_note(self) -> None:
        a = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ))
        c = _client()
        text = format_offset_ping(a, c, tz=TZ)
        assert text == "⏰ Через час: 14:00 · Олег"

    def test_late_prefix(self) -> None:
        a = _appt(datetime(2026, 5, 7, 14, 0, tzinfo=TZ))
        c = _client()
        text = format_offset_ping(a, c, tz=TZ, late=True)
        assert text.startswith("⏰ (с задержкой) ")
