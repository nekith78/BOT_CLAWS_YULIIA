"""Detect «I want to skip / leave empty» phrases the user might type or
say in place of an optional field's value.

Used by:
- AddAppointment note + instagram steps
- Intake text-input edit flow for the same fields

Phrases checked case-insensitively after .strip().lower(); any match
means the field should be left empty (None) instead of stored verbatim.
"""

from __future__ import annotations

_SKIP_PHRASES: frozenset[str] = frozenset(
    {
        # «Empty» words
        "пусто",
        "ничего",
        "никак",
        "—",
        "-",
        "",
        # «No» words
        "нет",
        "нету",
        "не",
        "no",
        # Explicit skip
        "пропусти",
        "пропустить",
        "skip",
        "пас",
        "пропуск",
        # Short colloquial
        "не надо",
        "не нужно",
        "без заметки",
        "без",
    }
)


def is_skip_phrase(text: str) -> bool:
    """Return True if `text` reads as «leave the field empty»."""
    cleaned = text.strip().lower()
    if cleaned in _SKIP_PHRASES:
        return True
    # Some users add a trailing period / quotes / spaces.
    cleaned = cleaned.strip(".!?,'\" ")
    return cleaned in _SKIP_PHRASES
