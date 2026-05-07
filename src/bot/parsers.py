"""Small text parsers shared between intake and wizard handlers.

Pure functions: no I/O, no LLM. Used to recognise common Russian
phrases before falling through to the LLM intake — keeps single-tap
inputs cheap and predictable.
"""

from __future__ import annotations

import re

_TIME_PATTERN = re.compile(r"(\d{1,2})\s*[:.\-_/ ]\s*(\d{2})")


def parse_time_from_text(raw: str) -> str | None:
    """Pull HH:MM out of free text. Whisper digit-formats Russian voice
    numbers («шестнадцать тридцать» → «16:30») reliably enough that this
    pattern catches most realistic inputs."""
    m = _TIME_PATTERN.search(raw)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if 0 <= hh < 24 and 0 <= mm < 60:
        return f"{hh:02d}:{mm:02d}"
    return None
