"""Concrete bot actions exposed to the LLM via tool-calling.

Note on layering: actions live in `services/intent/actions/` because
they belong to the intent layer conceptually. They DO import from `bot/`
(callback data, keyboards, formatters) — this is an intentional bend
of the strict `bot → services → storage` rule because actions are a
bridge between LLM intents and bot UI. New layer rule: only the intent
layer may reach into `bot/` for UI primitives; pure services must not.

Each action declares its `name`, `description`, JSON-schema `params_schema`,
and `confirm_required` flag. To add a new action:

    1. Create `<your_action>.py` here.
    2. Add it to the list in `register_default_actions` below.

The LLM will discover the new action automatically via `registry.tool_specs`.
"""

from src.services.intent.actions.bulk_cancel_by_client import BulkCancelByClientAction
from src.services.intent.actions.bulk_cancel_by_date import BulkCancelByDateAction
from src.services.intent.actions.bulk_delete_clients import BulkDeleteClientsAction
from src.services.intent.actions.cancel_appointment import CancelAppointmentAction
from src.services.intent.actions.count_appointments import CountAppointmentsAction
from src.services.intent.actions.count_client_appointments import (
    CountClientAppointmentsAction,
)
from src.services.intent.actions.count_clients import CountClientsAction
from src.services.intent.actions.create_appointment import CreateAppointmentAction
from src.services.intent.actions.delete_client import DeleteClientAction
from src.services.intent.actions.edit_note import EditNoteAction
from src.services.intent.actions.list_appointments import ListAppointmentsAction
from src.services.intent.actions.list_client_history import ListClientHistoryAction
from src.services.intent.actions.move_appointment import MoveAppointmentAction
from src.services.intent.registry import ActionRegistry


def register_default_actions(registry: ActionRegistry) -> None:
    """Register all bundled actions on `registry`. Called once at bot
    startup; tests build a fresh ActionRegistry and call this if the
    full action set is needed."""
    # Single-record actions.
    registry.register(CreateAppointmentAction())
    registry.register(MoveAppointmentAction())
    registry.register(CancelAppointmentAction())
    registry.register(EditNoteAction())
    registry.register(DeleteClientAction())
    # Read-only listings.
    registry.register(ListAppointmentsAction())
    registry.register(ListClientHistoryAction())
    # Aggregate counters (read-only).
    registry.register(CountClientsAction())
    registry.register(CountAppointmentsAction())
    registry.register(CountClientAppointmentsAction())
    # Bulk destructive operations (CONFIRM with full preview).
    registry.register(BulkCancelByDateAction())
    registry.register(BulkCancelByClientAction())
    registry.register(BulkDeleteClientsAction())


__all__ = [
    "BulkCancelByClientAction",
    "BulkCancelByDateAction",
    "BulkDeleteClientsAction",
    "CancelAppointmentAction",
    "CountAppointmentsAction",
    "CountClientAppointmentsAction",
    "CountClientsAction",
    "CreateAppointmentAction",
    "DeleteClientAction",
    "EditNoteAction",
    "ListAppointmentsAction",
    "ListClientHistoryAction",
    "MoveAppointmentAction",
    "register_default_actions",
]
