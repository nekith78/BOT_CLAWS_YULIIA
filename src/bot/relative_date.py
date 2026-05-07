"""Quick parser for Russian relative-date phrases.

Used by FSM wizard handlers to recognise «завтра» / «послезавтра» /
«в субботу» mid-step so the user doesn't have to back-button to the
date picker just to retype a date.

Pure function — no state, no LLM. Returns an ISO date string or None.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

# Lowercased weekday names indexed by weekday() (Mon=0 .. Sun=6).
_WEEKDAYS_LOWER = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
_WEEKDAY_FORMS: dict[str, int] = {}
for _idx, _root in enumerate(_WEEKDAYS_LOWER):
    # Accept the nominative form plus the «в <accusative>» form most
    # users actually type/say. e.g. «вторник», «во вторник», «в среду».
    _WEEKDAY_FORMS[_root] = _idx
# Common acc/insrumental forms.
_WEEKDAY_FORMS.update(
    {
        "понедельник": 0,
        "вторник": 1,
        "среду": 2,
        "среда": 2,
        "четверг": 3,
        "пятницу": 4,
        "пятница": 4,
        "субботу": 5,
        "суббота": 5,
        "воскресенье": 6,
    }
)


_DATE_PATTERN = re.compile(
    r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b"
)


def parse_relative_date(text: str, today: date) -> str | None:
    """Try to read a date out of `text`. Returns ISO YYYY-MM-DD or None.

    Handles:
    - «сегодня», «завтра», «послезавтра» / «после завтра»
    - «через неделю», «через 2 дня»
    - «в понедельник» / «во вторник» / «в среду» / ... (next occurrence,
      including today if today matches)
    - «8.05» / «8.05.2026» / «08.05.26»
    """
    cleaned = text.strip().lower()
    if not cleaned:
        return None

    if "сегодня" in cleaned:
        return today.isoformat()
    if "послезавтра" in cleaned or "после завтра" in cleaned:
        return (today + timedelta(days=2)).isoformat()
    if "завтра" in cleaned:
        return (today + timedelta(days=1)).isoformat()
    if "через неделю" in cleaned:
        return (today + timedelta(days=7)).isoformat()

    m_days = re.search(r"через\s+(\d+)\s+дн", cleaned)
    if m_days:
        return (today + timedelta(days=int(m_days.group(1)))).isoformat()

    for word, weekday_idx in _WEEKDAY_FORMS.items():
        # Word-boundary match so «среда» doesn't trigger inside «среди».
        if re.search(rf"\b{word}\b", cleaned):
            ahead = (weekday_idx - today.weekday()) % 7
            if ahead == 0:
                # Today matches — keep today unless user said «следующий»/«next».
                ahead = 7 if "следующ" in cleaned else 0
            return (today + timedelta(days=ahead)).isoformat()

    m_date = _DATE_PATTERN.search(cleaned)
    if m_date:
        try:
            day = int(m_date.group(1))
            month = int(m_date.group(2))
            year_raw = m_date.group(3)
            if year_raw:
                year = int(year_raw)
                if year < 100:
                    year += 2000
            else:
                year = today.year
                # Roll forward if «8.05» is already past in this year.
                tentative = date(year, month, day)
                if tentative < today:
                    year += 1
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    return None
