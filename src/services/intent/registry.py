"""Action registry — central catalog of voice/text-callable bot functions.

Each Action registers itself once; the registry produces the `ToolSpec`
list the LLM sees and dispatches `name → Action` lookups for the intake
handler.

A single global registry instance lives in `default_registry()`; concrete
actions register themselves there at import time. Tests can construct
their own empty `ActionRegistry` to avoid global state.
"""

from __future__ import annotations

from src.services.intent.types import Action, ToolSpec


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        """Add an action to the registry. Re-registering with the same
        name overwrites — useful for tests that swap implementations."""
        self._actions[action.name] = action

    def get(self, name: str) -> Action | None:
        return self._actions.get(name)

    def names(self) -> list[str]:
        return list(self._actions.keys())

    def tool_specs(self) -> list[ToolSpec]:
        """Build the tools list the LLM consumes via function-calling.
        Order matches registration order, which is reproducible because
        Python dicts preserve insertion order (3.7+)."""
        return [
            ToolSpec(
                name=a.name,
                description=a.description,
                params_schema=a.params_schema,
            )
            for a in self._actions.values()
        ]


_DEFAULT_REGISTRY: ActionRegistry | None = None


def default_registry() -> ActionRegistry:
    """The single registry shared by main.py and the intake handler.
    Constructed lazily so tests can swap or reset it as needed."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = ActionRegistry()
    return _DEFAULT_REGISTRY


def reset_default_registry() -> None:
    """Test helper — drop the cached default registry so the next
    `default_registry()` call returns a fresh empty one."""
    global _DEFAULT_REGISTRY
    _DEFAULT_REGISTRY = None
