"""text_parser — regex for /add command."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.services.parser.text_parser import ParseError, parse_add_command


class TestParseAddCommand:
    def test_full_form(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег @oleg_insta маникюр")
        assert result.starts_at == datetime(2026, 5, 6, 14, 30)
        assert result.client_name == "Олег"
        assert result.instagram == "oleg_insta"
        assert result.visit_note == "маникюр"

    def test_without_instagram(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег маникюр")
        assert result.client_name == "Олег"
        assert result.instagram is None
        assert result.visit_note == "маникюр"

    def test_without_note(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег @oleg_insta")
        assert result.visit_note is None
        assert result.instagram == "oleg_insta"

    def test_minimal(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег")
        assert result.client_name == "Олег"
        assert result.instagram is None
        assert result.visit_note is None

    def test_two_word_name_with_instagram(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег Иванов @oleg маникюр")
        assert result.client_name == "Олег Иванов"
        assert result.instagram == "oleg"
        assert result.visit_note == "маникюр"

    def test_instagram_at_optional(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег oleg_insta")
        # без @ — это просто часть имени/заметки, ig=None
        assert result.instagram is None

    def test_multi_word_note(self) -> None:
        result = parse_add_command("2026-05-06 14:30 Олег @oleg классический маникюр гель")
        assert result.client_name == "Олег"
        assert result.instagram == "oleg"
        assert result.visit_note == "классический маникюр гель"

    @pytest.mark.parametrize(
        "bad",
        [
            "не команда вообще",
            "2026-05-06 Олег",
            "2026/05/06 14:30 Олег",
            "2026-13-06 14:30 Олег",
            "2026-05-06 25:30 Олег",
            "2026-05-06 14:30",
        ],
    )
    def test_bad_inputs_raise(self, bad: str) -> None:
        with pytest.raises(ParseError):
            parse_add_command(bad)
