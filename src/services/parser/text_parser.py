"""Regex parser for the textual /add command."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


class ParseError(ValueError):
    """Raised when a string does not match the /add grammar."""


@dataclass(frozen=True)
class ParsedAdd:
    starts_at: datetime
    client_name: str
    instagram: str | None
    visit_note: str | None


_PATTERN = re.compile(
    r"^\s*"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2})\s+"
    r"(?P<rest>\S.*?)\s*$"
)


def parse_add_command(text: str) -> ParsedAdd:
    """Parse `YYYY-MM-DD HH:MM Name [@instagram] [visit note...]`.

    Name = leading consecutive capitalized tokens (`Иванов`, `John`).
    The first non-capitalized token starts the visit note.
    The first token is always treated as part of the name regardless of case.
    """
    m = _PATTERN.match(text)
    if not m:
        raise ParseError(f"Cannot parse: {text!r}")
    try:
        starts_at = datetime.strptime(f"{m['date']} {m['time']}", "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ParseError(str(exc)) from exc

    rest = m["rest"]
    ig_match = re.search(r"@([A-Za-z0-9._]+)", rest)
    instagram = ig_match.group(1) if ig_match else None

    if ig_match:
        rest = (rest[: ig_match.start()] + rest[ig_match.end() :]).strip()
        rest = re.sub(r"\s+", " ", rest)

    tokens = rest.split()
    if not tokens:
        raise ParseError("Client name is required")

    name_tokens = [tokens[0]]
    i = 1
    while i < len(tokens) and tokens[i][:1].isupper():
        name_tokens.append(tokens[i])
        i += 1
    client_name = " ".join(name_tokens)
    visit_note: str | None = " ".join(tokens[i:]) if i < len(tokens) else None

    return ParsedAdd(
        starts_at=starts_at,
        client_name=client_name,
        instagram=instagram,
        visit_note=visit_note,
    )
