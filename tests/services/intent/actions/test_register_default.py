"""Smoke test for `register_default_actions`."""

from __future__ import annotations

from src.services.intent.actions import register_default_actions
from src.services.intent.registry import ActionRegistry


def test_default_registration_includes_all_actions() -> None:
    registry = ActionRegistry()
    register_default_actions(registry)

    expected = {
        # Single-record
        "create_appointment",
        "move_appointment",
        "cancel_appointment",
        "edit_note",
        "delete_client",
        # Read-only listings
        "list_appointments",
        "list_client_history",
        # Aggregates
        "count_clients",
        "count_appointments",
        "count_client_appointments",
        # Bulk destructive
        "bulk_cancel_by_date",
        "bulk_cancel_by_client",
        "bulk_delete_clients",
    }
    assert set(registry.names()) == expected


def test_default_registration_emits_tool_specs() -> None:
    registry = ActionRegistry()
    register_default_actions(registry)

    specs = registry.tool_specs()
    assert len(specs) == 13
    for spec in specs:
        # All schemas must be objects (some have empty `properties` — count_clients
        # and bulk_delete_clients take no args).
        assert spec.params_schema.get("type") == "object"
        assert spec.description.strip() != ""
