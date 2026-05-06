"""Tests for ActionRegistry."""

from __future__ import annotations

from typing import Any, ClassVar

from src.services.intent.registry import (
    ActionRegistry,
    default_registry,
    reset_default_registry,
)
from src.services.intent.types import (
    Action,
    ActionContext,
    ActionResponse,
    ActionResult,
)


class _DummyAction:
    """Minimal Action implementation for tests."""

    name = "dummy"
    description = "dummy action for tests"
    confirm_required = False
    params_schema: ClassVar[dict[str, Any]] = {"type": "object"}

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        return ActionResponse(result=ActionResult.EXECUTED, text="ok")

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        return ActionResponse(result=ActionResult.EXECUTED, text="done")


class _AnotherAction:
    name = "another"
    description = "another action"
    confirm_required = True
    params_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
    }

    async def plan(
        self, ctx: ActionContext, args: dict[str, Any]
    ) -> ActionResponse:
        return ActionResponse(result=ActionResult.CONFIRM, text="ok")

    async def execute(
        self, ctx: ActionContext, payload: dict[str, Any]
    ) -> ActionResponse:
        return ActionResponse(result=ActionResult.EXECUTED, text="done")


def test_register_and_get_returns_same_instance() -> None:
    reg = ActionRegistry()
    a: Action = _DummyAction()
    reg.register(a)
    assert reg.get("dummy") is a


def test_get_unknown_returns_none() -> None:
    reg = ActionRegistry()
    assert reg.get("does-not-exist") is None


def test_register_overwrites_same_name() -> None:
    reg = ActionRegistry()
    first = _DummyAction()
    second = _DummyAction()
    reg.register(first)
    reg.register(second)
    assert reg.get("dummy") is second


def test_tool_specs_preserves_registration_order() -> None:
    reg = ActionRegistry()
    reg.register(_DummyAction())
    reg.register(_AnotherAction())
    specs = reg.tool_specs()
    names = [s.name for s in specs]
    assert names == ["dummy", "another"]


def test_tool_specs_carries_description_and_schema() -> None:
    reg = ActionRegistry()
    reg.register(_AnotherAction())
    spec = reg.tool_specs()[0]
    assert spec.name == "another"
    assert spec.description == "another action"
    assert spec.params_schema == {
        "type": "object",
        "properties": {"x": {"type": "string"}},
    }


def test_default_registry_is_singleton() -> None:
    reset_default_registry()
    a = default_registry()
    b = default_registry()
    assert a is b


def test_reset_default_registry_returns_fresh_instance() -> None:
    reset_default_registry()
    first = default_registry()
    first.register(_DummyAction())
    assert first.get("dummy") is not None

    reset_default_registry()
    second = default_registry()
    assert second is not first
    assert second.get("dummy") is None
