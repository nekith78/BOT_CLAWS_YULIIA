"""Shared data types for the intent layer.

Two groups of types live here:

1. **Parser-facing**: `ToolSpec` (LLM tool description), `ParsedIntent`
   (LLM result).

2. **Action-facing**: `ActionContext` (per-call deps), `ActionResponse` +
   `ActionResult` enum (what an Action returns), `Action` Protocol (the
   interface every concrete action implements).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import InlineKeyboardMarkup
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from sqlalchemy.ext.asyncio import AsyncSession


# --- Parser-facing types -------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """Function-calling description of one Action.

    `name` and `description` are read by the LLM. `params_schema` is a
    JSON-schema dict (object type with properties) — same shape as
    OpenAI's function-calling and Gemini's FunctionDeclaration.parameters.
    """

    name: str
    description: str
    params_schema: dict[str, Any]


@dataclass(frozen=True)
class ParsedIntent:
    """Result of `LLMProvider.parse_intent`.

    `tool_name=None` means the model didn't pick any tool — the user's
    text doesn't match any bot function. The caller shows a "не понял"
    response in that case.
    """

    tool_name: str | None
    args: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    rationale: str | None = None


# --- Action-facing types -------------------------------------------------


class ActionResult(str, Enum):
    """How the intake handler should react to an Action's response.

    `str` mixin (instead of 3.11+ StrEnum) keeps us 3.10-compatible while
    still supporting `value == "executed"` comparisons everywhere.
    """

    EXECUTED = "executed"     # done — send the result message, no follow-up
    CONFIRM = "confirm"       # show confirm-card, wait for ✅/✏️/❌
    CLARIFY = "clarify"       # ask user to disambiguate via inline buttons
    FAIL = "fail"             # parse-or-execute error — show text, abort


@dataclass(frozen=True)
class ActionResponse:
    """Return value of `Action.plan` and `Action.execute`."""

    result: ActionResult
    text: str
    keyboard: InlineKeyboardMarkup | None = None
    # `pending_payload` is what the handler stashes in FSM data when result is
    # CONFIRM or CLARIFY — it's passed back to `Action.execute` once the user
    # confirms, or back to `Action.plan` after disambiguation.
    pending_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class ActionContext:
    """Per-call dependencies. Built once per intake handler call and
    threaded into both `plan` and `execute`."""

    session: AsyncSession
    bot: Bot
    chat_id: int
    state: FSMContext
    scheduler: AsyncIOScheduler | None
    notify_runner: Any  # dotted path string; see notifications.scheduler.NOTIFY_RUNNER_PATH
    tz: ZoneInfo
    now_utc: datetime  # naive UTC, matches the rest of the codebase


@runtime_checkable
class Action(Protocol):
    """One bot function exposed to the LLM via tool-calling.

    Each concrete action declares its `name`, `description` and JSON-schema
    `params_schema` (used to build the `ToolSpec`). `confirm_required`
    decides whether the handler routes through a confirm-card before
    `execute` runs (destructive actions: True; read-only listings: False).
    """

    name: str
    description: str
    confirm_required: bool
    params_schema: dict[str, Any]

    async def plan(self, ctx: ActionContext, args: dict[str, Any]) -> ActionResponse: ...
    async def execute(self, ctx: ActionContext, payload: dict[str, Any]) -> ActionResponse: ...
