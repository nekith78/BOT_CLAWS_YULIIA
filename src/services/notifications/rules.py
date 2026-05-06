"""NotifyService — fire_at math and effective rule resolution.

`PlannedJob` is the in-memory description of *one* scheduled push for
*one* appointment. The persistence layer (`ScheduledJobRepository`) and
the runtime scheduler (APScheduler) both consume the same list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Appointment
from src.storage.repositories.appointment_notify_overrides import (
    AppointmentNotifyOverrideRepository,
)
from src.storage.repositories.notify_rules import NotifyRuleRepository

JobKind = Literal["eve_digest", "morning_digest", "offset_ping"]


@dataclass(frozen=True)
class PlannedJob:
    fire_at_utc: datetime  # naive UTC, matches the column type
    kind: JobKind
    rule_kind: str  # for debugging; one of: time_day_before / time_same_day / offset_before
    rule_value: str  # raw value, useful for telemetry


class RuleParseError(ValueError):
    """Raised when a rule value cannot be parsed."""


_OFFSET_PATTERN = re.compile(r"^\s*(\d+)\s*([mhd])\s*$")
_TIME_PATTERN = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")


def _parse_offset(value: str) -> timedelta:
    m = _OFFSET_PATTERN.match(value)
    if not m:
        raise RuleParseError(f"Cannot parse offset: {value!r}")
    n = int(m.group(1))
    unit = m.group(2)
    if unit == "m":
        return timedelta(minutes=n)
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(days=n)


def _parse_hhmm(value: str) -> time:
    m = _TIME_PATTERN.match(value)
    if not m:
        raise RuleParseError(f"Cannot parse HH:MM: {value!r}")
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise RuleParseError(f"Out-of-range HH:MM: {value!r}")
    return time(hour=hh, minute=mm)


def _kind_to_job_kind(rule_kind: str) -> JobKind:
    if rule_kind == "time_day_before":
        return "eve_digest"
    if rule_kind == "time_same_day":
        return "morning_digest"
    if rule_kind == "offset_before":
        return "offset_ping"
    raise RuleParseError(f"Unknown rule kind: {rule_kind!r}")


async def effective_rules_for_appointment(
    session: AsyncSession, appointment_id: int
) -> list[tuple[str, str, bool]]:
    """If the appointment has any override rows, return them as the full
    rule set (overrides totally replace globals for this appointment).
    Otherwise return the enabled global notify_rules.

    Disabled rows are kept in the result so callers can show them in the
    UI; the planner filters them out itself.
    """
    overrides = await AppointmentNotifyOverrideRepository(session).list_for_appointment(
        appointment_id
    )
    if overrides:
        return [(r.kind, r.value, r.enabled) for r in overrides]

    globals_ = await NotifyRuleRepository(session).list_all()
    return [(r.kind, r.value, r.enabled) for r in globals_]


def _appt_starts_at_utc(appt: Appointment) -> datetime:
    """The schema stores starts_at as UTC-naive. Re-attach UTC before tz math."""
    if appt.starts_at.tzinfo is None:
        return appt.starts_at.replace(tzinfo=timezone.utc).replace(tzinfo=None) + timedelta(0)
    return appt.starts_at.astimezone(timezone.utc).replace(tzinfo=None)


async def plan_jobs(
    session: AsyncSession,
    appointment: Appointment,
    *,
    tz: ZoneInfo,
    now_utc: datetime,
) -> list[PlannedJob]:
    """Compute the list of PlannedJob for this appointment using its
    effective rules. Past fire_ats (≤ now_utc) are dropped to avoid
    queuing already-missed work.
    """
    rules = await effective_rules_for_appointment(session, appointment.id)
    starts_at_utc = _appt_starts_at_utc(appointment)
    starts_at_utc_aware = starts_at_utc.replace(tzinfo=timezone.utc)
    starts_at_local = starts_at_utc_aware.astimezone(tz)

    out: list[PlannedJob] = []
    for kind, value, enabled in rules:
        if not enabled:
            continue
        try:
            if kind == "time_day_before":
                hhmm = _parse_hhmm(value)
                local_dt = datetime.combine(
                    starts_at_local.date() - timedelta(days=1),
                    hhmm,
                    tzinfo=tz,
                )
                fire_utc = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
            elif kind == "time_same_day":
                hhmm = _parse_hhmm(value)
                local_dt = datetime.combine(
                    starts_at_local.date(), hhmm, tzinfo=tz
                )
                fire_utc = local_dt.astimezone(timezone.utc).replace(tzinfo=None)
            elif kind == "offset_before":
                fire_utc = starts_at_utc - _parse_offset(value)
            else:
                continue  # unknown — silently ignore
        except RuleParseError:
            continue

        if fire_utc <= now_utc:
            continue

        out.append(
            PlannedJob(
                fire_at_utc=fire_utc,
                kind=_kind_to_job_kind(kind),
                rule_kind=kind,
                rule_value=value,
            )
        )
    return out
