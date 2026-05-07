"""Tests for parse_relative_date."""

from __future__ import annotations

from datetime import date

import pytest

from src.bot.relative_date import parse_relative_date


# Anchor: Thursday 2026-05-07.
TODAY = date(2026, 5, 7)


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("сегодня", "2026-05-07"),
        ("Сегодня вечером", "2026-05-07"),
        ("завтра", "2026-05-08"),
        ("на завтра в 14", "2026-05-08"),
        ("послезавтра", "2026-05-09"),
        ("после завтра", "2026-05-09"),
        ("через неделю", "2026-05-14"),
        ("через 3 дня", "2026-05-10"),
        # Weekdays (TODAY is Thursday → next Thursday is in 7 days; Mon is +4)
        ("в понедельник", "2026-05-11"),
        ("во вторник", "2026-05-12"),
        ("в среду", "2026-05-13"),
        ("в пятницу", "2026-05-08"),
        ("в субботу", "2026-05-09"),
        ("в воскресенье", "2026-05-10"),
        # Numeric date — same year
        ("8.05", "2026-05-08"),
        ("08.05", "2026-05-08"),
        ("8.05.2026", "2026-05-08"),
        ("8.05.26", "2026-05-08"),
    ],
)
def test_recognised_dates(phrase: str, expected: str) -> None:
    assert parse_relative_date(phrase, TODAY) == expected


def test_numeric_date_in_past_rolls_to_next_year() -> None:
    """8.04 (when today is 7.05) → already past → 2027-04-08."""
    assert parse_relative_date("8.04", TODAY) == "2027-04-08"


@pytest.mark.parametrize(
    "phrase",
    [
        "",
        "16:30",
        "френч",
        "ничего интересного",
        "среди недели",  # «среди» must NOT trigger «среда»
    ],
)
def test_unrecognised(phrase: str) -> None:
    assert parse_relative_date(phrase, TODAY) is None
