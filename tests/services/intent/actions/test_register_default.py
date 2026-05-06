"""Smoke test for `register_default_actions`."""

from __future__ import annotations

from src.services.intent.actions import register_default_actions
from src.services.intent.registry import ActionRegistry


def test_default_registration_includes_all_seven_actions() -> None:
    registry = ActionRegistry()
    register_default_actions(registry)

    expected = {
        "create_appointment",
        "list_appointments",
        "move_appointment",
        "cancel_appointment",
        "edit_note",
        "list_client_history",
        "delete_client",
    }
    assert set(registry.names()) == expected


def test_default_registration_emits_tool_specs() -> None:
    registry = ActionRegistry()
    register_default_actions(registry)

    specs = registry.tool_specs()
    assert len(specs) == 7
    for spec in specs:
        # All schemas must be objects with at least one property.
        assert spec.params_schema.get("type") == "object"
        assert spec.description.strip() != ""
