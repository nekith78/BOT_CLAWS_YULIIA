"""Notifications service layer.

Public entry points re-exported for handler-side use:
- reschedule_for_appointment: rebuild scheduled_jobs + APScheduler jobs after
  the appointment was created/moved.
- cancel_for_appointment: drop scheduled_jobs + APScheduler jobs after
  cancel/delete.
"""

from src.services.notifications.scheduler_glue import (
    cancel_for_appointment,
    reschedule_for_appointment,
)

__all__ = ["cancel_for_appointment", "reschedule_for_appointment"]
